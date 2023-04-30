import asyncio

from datetime import datetime, timedelta

from pyppeteer.errors import PyppeteerError

from travian.bot_functions import TravianBotFunction

from settings import DATE_TIME_FORMAT

from typing import Optional
from types import SimpleNamespace

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from travian.bot import TravianBot

import logging

logger = logging.getLogger(__name__)

TaskStatus = SimpleNamespace(
    Created='created',
    Scheduled='scheduled',
    Running='running',
    Completed='completed',
    Cancelled='cancelled',
    Failed='failed',
)


class FunctionTask:

    def __init__(self, function: TravianBotFunction, scheduler: 'TaskScheduler', run_async=False, reschedule_on_error=True, max_retries=1, retry_seconds=0):
        self.function = function
        self._scheduler = scheduler
        self._run_async = run_async
        self._status = TaskStatus.Created
        self.reschedule_on_error = reschedule_on_error
        self.max_retries = max_retries if max_retries >= 0 else 1
        self.retry_seconds = retry_seconds if retry_seconds >= 0 else 0
        self.__cancellable_task: Optional[asyncio.Future] = None
        self.__from_schedule: Optional[asyncio.Queue['FunctionTask']] = None
        self.__finish_event = asyncio.Event()
        self.exception = None
        self._retries = 0

    @property
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, new_status: str):
        if new_status != self._status and not self.__finish_event.is_set():
            self._status = new_status
            self._on_new_status()

    def _on_new_status(self):
        if self._status == TaskStatus.Failed:
            logger.error(f'{self}: {self.exception}')
        elif self._status == TaskStatus.Cancelled:
            logger.warning(self)
        else:
            logger.info(self)

    @property
    def from_schedule(self) -> Optional[asyncio.Queue['FunctionTask']]:
        return self.__from_schedule

    @from_schedule.setter
    def from_schedule(self, queue: Optional[asyncio.Queue['FunctionTask']]):
        if queue and self.__from_schedule:
            raise ValueError(f'{self} already scheduled')

        self.__from_schedule = queue

        if self.__from_schedule:
            self.status = TaskStatus.Scheduled

    @property
    def is_asynchronous(self) -> bool:
        return self._run_async

    async def run(self):
        if self.is_cancelled:
            raise asyncio.CancelledError(f'{self.function} is cancelled')

        self.exception = None

        self.status = TaskStatus.Running

        try:
            self.__cancellable_task = asyncio.ensure_future(self._run(), loop=self._scheduler._event_loop)
            await self.__cancellable_task
            self._finish(TaskStatus.Completed)
        except asyncio.CancelledError:
            self._finish(TaskStatus.Cancelled)
        except BaseException as e:
            await self._failed(e)

    async def _run(self):
        await self.function.run()

    @property
    def is_running(self) -> bool:
        return self._status == TaskStatus.Running

    @property
    def is_completed(self) -> bool:
        return self._status == TaskStatus.Completed

    @property
    def is_cancelled(self) -> bool:
        return self._status == TaskStatus.Cancelled

    @property
    def is_failed(self) -> bool:
        return self._status == TaskStatus.Failed

    @property
    def is_finished(self) -> bool:
        return self.is_completed or self.is_cancelled or self.is_failed

    def cancel(self):
        if self.__cancellable_task and not self.__cancellable_task.cancelled():
            self.__cancellable_task.cancel()
            self.__cancellable_task = None

        self._finish(TaskStatus.Cancelled)

    def _finish(self, status: str):
        self.status = status

        self.__cancellable_task = None

        if self.is_finished and self.from_schedule:
            self.from_schedule.task_done()
            self.from_schedule = None
            self.__finish_event.set()

    async def _failed(self, e: BaseException):
        self.exception = e

        if not isinstance(e, (PyppeteerError, asyncio.TimeoutError, asyncio.InvalidStateError)):
            logger.warning(f'Unknown Error [{e.__class__.__qualname__}]')
            self._finish(TaskStatus.Failed)
            raise e

        self.status = TaskStatus.Failed

        schedule_retry_task = await self._schedule_retry()

        schedule_retry_task.add_done_callback(lambda _: self._finish(TaskStatus.Failed))

    async def _schedule_retry(self) -> asyncio.Task:
        if self.reschedule_on_error and self._retries < self.max_retries:
            self._retries += 1

            logger.debug(
                f"{self} RETRY ({self._retries}){f' in {self.retry_seconds} seconds...' if self.retry_seconds > 0 else ''}")

            if self.retry_seconds > 0:
                await asyncio.sleep(self.retry_seconds)

            return self._scheduler._append_retry(self.copy())

        return EmptyTask(self._scheduler)

    async def wait(self):
        await self.__finish_event.wait()

    def __str__(self):
        return f'{self.function} ({self.status})'

    def copy(self) -> 'FunctionTask':
        function_task = FunctionTask(self.function, self._scheduler, self._run_async,
                                     self.reschedule_on_error, self.max_retries, self.retry_seconds)
        function_task._retries = self._retries
        return function_task


class PeriodicTask(FunctionTask):

    def __init__(self, function: TravianBotFunction, scheduler: 'TaskScheduler', interval_seconds: int,
                 blocking=False, reschedule_on_error=False, max_retries=2, retry_seconds=5):
        super().__init__(function, scheduler, run_async=True, reschedule_on_error=reschedule_on_error,
                         max_retries=max_retries, retry_seconds=retry_seconds)

        if interval_seconds is None or type(interval_seconds) is not int or interval_seconds <= 0:
            raise ValueError(f'Invalid interval for {function}')

        self.interval_seconds = interval_seconds
        self.blocking = blocking
        self._next_at = None
        self.__wait_cancellable_task: Optional[asyncio.Future] = None

    @property
    def is_finished(self):
        return self.is_cancelled or self.is_failed

    async def run(self):
        while not self.is_finished:
            self._next_at = None

            if self.blocking:
                # START -> FINISH -> WAIT (interval_seconds) -> START ...
                # Waits after the task finishes, time shifts with task duration
                # Blocks until task finishes
                await asyncio.ensure_future(self.run_blocking(), loop=self._scheduler._event_loop)
            else:
                # START -> WAIT (RUNNING) -> FINISH -> WAIT (Remaining: interval_seconds - task duration) -> START ...
                # Waits concurrently, time syncs with task start (may shift from single thread concurrency)
                # If task elapses more than interval seconds then blocks until task finishes
                self.__wait_cancellable_task = asyncio.ensure_future(self.__wait(), loop=self._scheduler._event_loop)

                try:
                    await asyncio.gather(
                        asyncio.ensure_future(super().run(), loop=self._scheduler._event_loop),
                        self.__wait_cancellable_task,
                    )
                except asyncio.CancelledError:
                    pass

    async def run_blocking(self):
        await super().run()

        if not self.is_finished:
            self.__set_next_at()
            self.status = TaskStatus.Scheduled
            self.__wait_cancellable_task = asyncio.ensure_future(self.__wait(), loop=self._scheduler._event_loop)
            try:
                await self.__wait_cancellable_task
            except asyncio.CancelledError:
                pass

    async def __wait(self):
        await asyncio.sleep(self.interval_seconds)

    def cancel(self):
        super().cancel()

        if self.__wait_cancellable_task:
            self.__wait_cancellable_task.cancel()

    def _on_new_status(self):
        if self._status == TaskStatus.Running:
            if not self.blocking:
                self.__set_next_at()

        elif self._status == TaskStatus.Completed and not self.blocking:
            self._status = TaskStatus.Scheduled

        elif self._status == TaskStatus.Failed:
            self._next_at = None

            if self.__wait_cancellable_task:
                self.__wait_cancellable_task.cancel()

        super()._on_new_status()

    def __set_next_at(self):
        if not self._next_at:
            self._next_at = datetime.now() + timedelta(seconds=self.interval_seconds)

    async def _schedule_retry(self):
        if self.reschedule_on_error and self._retries >= self.max_retries:
            new_task = self.copy()
            new_task._retries = 0

            retry_at = datetime.now() + timedelta(seconds=self.interval_seconds)

            logger.debug(f'{self} RETRY AT {retry_at.strftime(DATE_TIME_FORMAT)}')

            return self._scheduler._schedule(new_task, retry_at, queue=self._scheduler._failed_queue)

        return await super()._schedule_retry()

    def __str__(self):
        s = super().__str__()

        if self._next_at and self._status == TaskStatus.Scheduled:
            s += f' next at {self._next_at.strftime(DATE_TIME_FORMAT)}'

        return s

    def copy(self) -> 'PeriodicTask':
        function_task = PeriodicTask(self.function, self._scheduler, self.interval_seconds, self.blocking,
                                     self.reschedule_on_error, self.max_retries, self.retry_seconds)
        function_task._retries = self._retries
        return function_task


class ScheduleTask(FunctionTask):

    def __init__(self, scheduler: 'TaskScheduler', task: FunctionTask, at: datetime, priority: bool = False, max_retries: int = 2, retry_seconds: int = 5):
        super().__init__(task.function, scheduler, run_async=True, max_retries=max_retries, retry_seconds=retry_seconds)
        self.priority = priority
        self._task = task
        self.at = at

    async def _run(self):
        await self._wait_schedule()

        if self.priority:
            await self._scheduler._run(self._task)
        else:
            await self._scheduler._append(self._task)

    async def _wait_schedule(self):
        remaining_seconds = self.remaining_seconds()

        if remaining_seconds > 0:
            await asyncio.sleep(remaining_seconds)

    def remaining_seconds(self) -> float:
        return (self.at - datetime.now()).total_seconds()

    def _on_new_status(self):
        if self._status == TaskStatus.Running:
            self._status = TaskStatus.Scheduled
            super()._on_new_status()
        elif self._status == TaskStatus.Failed:
            super()._on_new_status()

    def cancel(self):
        super().cancel()
        self._task.cancel()

    def __str__(self):
        s = super().__str__()

        if self._status == TaskStatus.Scheduled and self.remaining_seconds() > 0:
            aprox = '~' if not self.priority else ''
            s += f' will run at {aprox}{self.at.strftime(DATE_TIME_FORMAT)}'

        return s

    def copy(self) -> 'ScheduleTask':
        function_task = ScheduleTask(self._scheduler, self._task, self.at,
                                     self.priority, self.max_retries, self.retry_seconds)
        function_task._retries = self._retries
        return function_task

    @staticmethod
    def wrap_schedule_task(scheduler: 'TaskScheduler', task: FunctionTask, at: datetime, priority: bool = False) -> 'ScheduleTask':
        return ScheduleTask(scheduler, task, at, priority)


class EmptyTask(asyncio.Task):

    def __init__(self, scheduler: 'TaskScheduler'):
        super().__init__(self.done(), loop=scheduler._event_loop)

    async def done(self):
        return True


class TaskScheduler:

    def __init__(self, bot: 'TravianBot'):
        self._bot = bot
        self._queue: asyncio.Queue[FunctionTask] = asyncio.Queue()
        self._failed_queue: asyncio.Queue[FunctionTask] = asyncio.Queue()
        self._running_tasks: set[FunctionTask] = set()
        self._waiting: Optional[asyncio.Future] = None

    @property
    def _event_loop(self):
        return self._bot._event_loop

    def append(self, function: TravianBotFunction,
               interval_seconds: Optional[int] = None, blocking: bool = False,
               reschedule_on_error: bool = True, max_retries: Optional[int] = 2, retry_seconds: Optional[int] = 5) -> asyncio.Task:
        return self._append(self.wrap_task(function, interval_seconds, blocking, reschedule_on_error, max_retries, retry_seconds))

    def schedule(self, function: TravianBotFunction, at: datetime, priority: bool = False,
                 interval_seconds: Optional[int] = None, blocking: bool = False,
                 reschedule_on_error: bool = True, max_retries: Optional[int] = 2, retry_seconds: Optional[int] = 5) -> asyncio.Task:
        return self._schedule(self.wrap_task(function, interval_seconds, blocking, reschedule_on_error, max_retries, retry_seconds), at, priority)

    def _schedule(self, function_task: FunctionTask, at: datetime, priority: bool = False,
                  queue: Optional[asyncio.Queue[FunctionTask]] = None) -> asyncio.Task:
        return self._append(ScheduleTask.wrap_schedule_task(self, function_task, at, priority), queue)

    def _append_retry(self, function_task: FunctionTask) -> asyncio.Task:
        return self._append(function_task, self._failed_queue)

    def _append(self, function_task: FunctionTask, queue: Optional[asyncio.Queue[FunctionTask]] = None) -> asyncio.Task:
        return self._event_loop.create_task(self.__append_async(function_task, queue))

    async def __append_async(self, function_task: FunctionTask, queue: Optional[asyncio.Queue[FunctionTask]]):
        if not function_task.is_cancelled and not self._bot.is_stopped and not self._bot.is_stopping:
            queue = queue or self._queue
            await queue.put(function_task)
            function_task.from_schedule = queue
            await self.__notify_queue()

    async def run(self, function: TravianBotFunction,
                  interval_seconds: Optional[int] = None, blocking: bool = False,
                  reschedule_on_error: bool = True, max_retries: Optional[int] = 2, retry_seconds: Optional[int] = 5) -> asyncio.Task:
        return await self._run(self.wrap_task(function, interval_seconds, blocking, reschedule_on_error, max_retries, retry_seconds))

    async def _run(self, function_task: FunctionTask) -> asyncio.Task:
        running_task = self.__run_task(function_task)

        try:
            if not function_task.is_asynchronous:
                await running_task
        except asyncio.CancelledError:
            function_task.cancel()
            running_task.cancel()

        return running_task

    def __run_task(self, function_task: FunctionTask) -> asyncio.Task:
        self._running_tasks.add(function_task)

        task = self._event_loop.create_task(function_task.run())

        def finish_task(_: asyncio.Task):
            if function_task.is_running:
                raise ValueError('Finished task when still running')

            self._running_tasks.remove(function_task)

        task.add_done_callback(finish_task)

        return task

    async def loop(self):
        await self.wait_for_running_tasks()

        logger.debug(f'Starting loop')

        while len(self) > 0 or self.running_tasks:
            await self.__run_scheduled_tasks()

            await self.wait_for_running_tasks()

        logger.debug(f'Loop finished')

    async def __run_scheduled_tasks(self):
        while len(self) > 0:
            queue = self._failed_queue if not self._failed_queue.empty() else self._queue
            function_task = queue.get_nowait()
            await self._run(function_task)

    @property
    def is_waiting(self) -> bool:
        return self._waiting is not None and not self._waiting.done()

    async def wait_for_running_tasks(self):
        if not self.is_waiting and self.running_tasks:
            if self._waiting is None:
                self._waiting = asyncio.ensure_future(self.__wait_for_running_tasks())
            await self._waiting
            self._waiting = None

    async def __wait_for_running_tasks(self):
        await self.__wait_for_queues()

        if self.running_tasks:
            logger.debug(f'Waiting for {len(self.running_tasks)} scheduled tasks...')

            while self.running_tasks:
                await self.__wait_for_queues()

    async def __wait_for_queues(self):
        await asyncio.gather(
            self._queue.join(),
            self._failed_queue.join()
        )

    async def __notify_queue(self):
        if self.is_waiting:
            await self.__run_scheduled_tasks()

    async def clear(self, cancel_running_tasks=False):
        self.__clear_queue(self._failed_queue)
        self.__clear_queue(self._queue)

        if cancel_running_tasks:
            running_tasks = self._running_tasks.copy()

            for running_task in running_tasks:
                running_task.cancel()

        await self.wait_for_running_tasks()

    @staticmethod
    def __clear_queue(queue: asyncio.Queue[FunctionTask]):
        while not queue.empty():
            function_task = queue.get_nowait()
            queue.task_done()  # skip running this task
            logger.debug(f'Skip {function_task}')

    @property
    def running_tasks(self) -> set[FunctionTask]:
        return self._running_tasks

    @property
    def active_tasks(self) -> set[FunctionTask]:
        return {running_task for running_task in self.running_tasks if running_task.is_running}

    def __len__(self):
        return self._queue.qsize() + self._failed_queue.qsize()  # scheduled tasks

    def wrap_task(self, function: TravianBotFunction,
                  interval_seconds: Optional[int] = None, blocking: bool = False,
                  reschedule_on_error: bool = True, max_retries: Optional[int] = 2, retry_seconds: Optional[int] = 5) -> FunctionTask:
        max_retries = 2 if max_retries is None else max_retries
        retry_seconds = 5 if retry_seconds is None else retry_seconds
        if interval_seconds is not None:
            return PeriodicTask(function, self, interval_seconds=interval_seconds, blocking=blocking,
                                reschedule_on_error=reschedule_on_error, max_retries=2 if max_retries is None else max_retries, retry_seconds=retry_seconds)
        return FunctionTask(function, self, reschedule_on_error=reschedule_on_error, max_retries=max_retries, retry_seconds=retry_seconds)
