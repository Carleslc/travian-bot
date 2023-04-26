from collections import deque

from pyppeteer.errors import PyppeteerError, TimeoutError

from types import SimpleNamespace

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from travian.bot_functions import TravianBotFunction

import logging

logger = logging.getLogger(__name__)


class FunctionTask:

    TaskStatus = SimpleNamespace(
        Created='created',
        Scheduled='scheduled',
        Running='running',
        Completed='completed',
        Failed='failed',
    )

    def __init__(self, function: 'TravianBotFunction'):
        self.function = function
        self.status = FunctionTask.TaskStatus.Created

    async def run(self):
        self.status = FunctionTask.TaskStatus.Running
        try:
            logger.info(self)
            await self.function.run()
        except Exception as e:
            self.status = FunctionTask.TaskStatus.Failed
            raise e
        self.status = FunctionTask.TaskStatus.Completed

    def __repr__(self):
        return f'{self.function} ({self.status})'


class TaskQueue:

    def __init__(self):
        self.queue: deque['FunctionTask'] = deque([])
        self.current_task: Optional['FunctionTask'] = None

    def append(self, function: 'TravianBotFunction'):
        task = FunctionTask(function)
        self.queue.append(task)
        task.status = FunctionTask.TaskStatus.Scheduled
        logger.info(task)

    def __prepend(self, task: 'FunctionTask'):
        self.queue.appendleft(task)
        task.status = FunctionTask.TaskStatus.Scheduled

    async def loop(self):
        while len(self) > 0:
            self.current_task = self.queue.popleft()
            try:
                await self.current_task.run()
            except (PyppeteerError, TimeoutError) as e:
                logger.error(f'{self.current_task}: {e}')
                self.__prepend(self.current_task)
        self.current_task = None

    def __len__(self):
        return len(self.queue)
