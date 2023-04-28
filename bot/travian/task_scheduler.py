import asyncio

from datetime import datetime, timedelta

from pyppeteer.errors import PyppeteerError, TimeoutError

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

    def __init__(self, function: TravianBotFunction, run_async=False, reschedule_on_error=True):
        self.function = function
        self._run_async = run_async
        self._status = TaskStatus.Created
        self.cancellable_task: Optional[asyncio.Future] = None
        self.reschedule_on_error = reschedule_on_error
        self.from_schedule = False
        self.exception = None

    @property
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, new_status: str):
        if not self.is_cancelled and new_status != self._status:
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
    def is_asynchronous(self) -> bool:
        return self._run_async

    async def run(self):
        if self.is_cancelled:
            raise ValueError(f'{self.function} is cancelled')

        self.status = TaskStatus.Running

        try:
            await self._run()
        except Exception as e:
            self.exception = e
            self.status = TaskStatus.Failed
            raise self.exception

        self.status = TaskStatus.Completed

    async def _run(self):
        await self.function.run()

    @property
    def is_cancelled(self):
        return self._status == TaskStatus.Cancelled

    def cancel(self):
        self.status = TaskStatus.Cancelled

        if self.cancellable_task and not self.cancellable_task.cancelled():
            self.cancellable_task.cancel()
            self.cancellable_task = None

    @property
    def is_finished(self):
        return self._status == TaskStatus.Completed \
            or self._status == TaskStatus.Cancelled \
            or self._status == TaskStatus.Failed

    def __str__(self):
        return f'{self.function} ({self.status})'


class PeriodicTask(FunctionTask):

    def __init__(self, function: TravianBotFunction, interval_seconds: int, reschedule_on_error=False):
        super().__init__(function, run_async=True, reschedule_on_error=reschedule_on_error)

        if interval_seconds is None or type(interval_seconds) is not int or interval_seconds <= 0:
            raise ValueError(f'Invalid interval for {function}')

        self.interval_seconds = interval_seconds
        self._sleep_task = None
        self._next_at = None

    async def run(self):
        while not self.is_cancelled:
            self.cancellable_task = asyncio.ensure_future(super().run())
            self._sleep_task = asyncio.ensure_future(asyncio.sleep(self.interval_seconds))

            await asyncio.gather(
                self.cancellable_task,
                self._sleep_task,
            )

    def cancel(self):
        super().cancel()

        if self._sleep_task:
            self._sleep_task.cancel()

    @property
    def is_finished(self):
        return self.is_cancelled

    def _on_new_status(self):
        super()._on_new_status()

        if self._status == TaskStatus.Running:
            self._next_at = datetime.now() + timedelta(seconds=self.interval_seconds)
        elif self._status == TaskStatus.Completed:
            self.status = TaskStatus.Scheduled

    def __str__(self):
        s = super().__str__()

        if self._next_at and self._status == TaskStatus.Scheduled:
            s += f' next at {self._next_at.strftime(DATE_TIME_FORMAT)}'

        return s


class ScheduleTask(FunctionTask):

    def __init__(self, scheduler: 'TaskScheduler', task: FunctionTask, at: datetime, priority: bool = False):
        super().__init__(task.function, run_async=True)
        self.scheduler = scheduler
        self.priority = priority
        self._task = task
        self.at = at

    async def _run(self):
        await self._wait_schedule()

        if self.priority:
            await self.scheduler._run(self._task)
        else:
            await self.scheduler._append(self._task)

    async def _wait_schedule(self):
        now = datetime.now()
        remaining_seconds = (self.at - now).total_seconds()

        if remaining_seconds > 0:
            self._log_schedule()
            await asyncio.sleep(remaining_seconds)

    def _on_new_status(self):
        if self._status == TaskStatus.Failed:
            super()._on_new_status()

    def cancel(self):
        super().cancel()
        self._task.cancel()

    @property
    def is_finished(self):
        return self._task.is_finished

    def _log_schedule(self):
        aprox = '~' if not self.priority else ''
        logger.info(f'{self.function} ({TaskStatus.Scheduled}) will run at {aprox}{self.at.strftime(DATE_TIME_FORMAT)}')

    @staticmethod
    def wrap_schedule_task(scheduler: 'TaskScheduler', task: FunctionTask, at: datetime, priority: bool = False) -> 'ScheduleTask':
        return ScheduleTask(scheduler, task, at, priority)


class TaskScheduler:

    def __init__(self, bot: 'TravianBot'):
        self._bot = bot
        self._queue: asyncio.Queue[FunctionTask] = asyncio.Queue()
        self._running_tasks: set[FunctionTask] = set()
        self._waiting: Optional[asyncio.Future] = None

    @property
    def _event_loop(self):
        return self._bot._event_loop

    async def append(self, function: TravianBotFunction,
                     interval_seconds: Optional[int] = None, reschedule_on_error: Optional[bool] = None):
        await self._append(wrap_task(function, interval_seconds, reschedule_on_error))

    async def schedule(self, function: TravianBotFunction, at: datetime, priority: bool = False,
                       interval_seconds: Optional[int] = None, reschedule_on_error: Optional[bool] = None):
        function_task = wrap_task(function, interval_seconds, reschedule_on_error)
        await self._append(ScheduleTask.wrap_schedule_task(self, function_task, at, priority))

    async def _append(self, function_task: FunctionTask):
        if not function_task.is_cancelled and not self._bot.is_stopping:
            await self._queue.put(function_task)
            function_task.from_schedule = True
            function_task.status = TaskStatus.Scheduled
            await self.__check_queue()

    async def run(self, function: TravianBotFunction,
                  interval_seconds: Optional[int] = None, reschedule_on_error: Optional[bool] = None):
        await self._run(wrap_task(function, interval_seconds, reschedule_on_error))

    async def _run(self, function_task: FunctionTask):
        running_task = self.__run_task(function_task)

        try:
            if not function_task.is_asynchronous:
                await running_task
        except asyncio.exceptions.CancelledError:
            function_task.cancel()

    def __run_task(self, function_task: FunctionTask) -> asyncio.Future:
        self._running_tasks.add(function_task)

        function_task.cancellable_task = self._event_loop.create_task(
            self.__run_async(function_task)
        )

        function_task.cancellable_task.add_done_callback(
            lambda _: self.__finish_task(function_task)
        )

        return function_task.cancellable_task

    async def __run_async(self, function_task: FunctionTask):
        try:
            await function_task.run()
        except (PyppeteerError, TimeoutError):
            if function_task.reschedule_on_error:
                await self._append(function_task)

    def __finish_task(self, function_task: FunctionTask):
        if function_task.status == TaskStatus.Running:
            raise ValueError('Finished task when still running')

        self._running_tasks.remove(function_task)

        if function_task.from_schedule:
            self._queue.task_done()

    async def loop(self):
        await self.wait_for_running_tasks()

        logger.debug(f'Starting loop')

        await self.__loop()

        logger.debug(f'Loop finished')

    async def __loop(self):
        while not self._queue.empty():
            function_task = self._queue.get_nowait()
            await self._run(function_task)

        await self.wait_for_running_tasks()

    async def __check_queue(self):
        if self._waiting:
            await self.__loop()  # restart loop after new tasks are scheduled

    async def clear(self, cancel_running_tasks=False):
        self.__clear_queue()

        if cancel_running_tasks:
            running_tasks = self._running_tasks.copy()

            for running_task in running_tasks:
                running_task.cancel()

        await self.wait_for_running_tasks()

    def __clear_queue(self):
        while not self._queue.empty():
            function_task = self._queue.get_nowait()
            self._queue.task_done()  # skip running this task
            logger.debug(f'Skip {function_task}')

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
        logger.debug('Waiting for running tasks...')
        # wait to finish scheduled tasks
        await self._queue.join()
        logger.debug('All scheduled tasks finished')

        def running_tasks_async():
            return [running_task.cancellable_task for running_task in self._running_tasks if running_task.cancellable_task is not None and not running_task.is_cancelled]

        running_tasks = running_tasks_async()

        were_non_scheduled_remaining = len(running_tasks) > 0

        while running_tasks:
            # wait to finish isolated tasks (not put on the queue)
            logger.debug(
                f'There are still {len(running_tasks)} isolated running tasks, waiting to finish...')

            await asyncio.gather(*running_tasks)

            running_tasks = running_tasks_async()

        if were_non_scheduled_remaining:
            logger.debug('All isolated tasks finished')

    @property
    def running_tasks(self):
        return len(self._running_tasks)

    def __len__(self):
        return self._queue.qsize()  # scheduled tasks


def wrap_task(function: TravianBotFunction, interval_seconds: Optional[int] = None, reschedule_on_error: Optional[bool] = None) -> FunctionTask:
    if interval_seconds is not None:
        return PeriodicTask(function, interval_seconds, reschedule_on_error=reschedule_on_error or False)
    return FunctionTask(function, reschedule_on_error=True if reschedule_on_error is None else reschedule_on_error)
