from django.apps import AppConfig
import logging
import os
import sys
import threading
import time

logger = logging.getLogger(__name__)
_dev_scheduler_started = False
_dev_scheduler_lock = threading.Lock()

class CampaignsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'campaigns'

    def ready(self):
        """
        Dev fallback scheduler:
        When Celery eager mode is enabled and no worker/beat is running,
        execute campaign processing + reply polling in-process so delayed steps
        and reply tracking still work locally.
        """
        from django.conf import settings

        if not settings.DEBUG or not settings.CELERY_TASK_ALWAYS_EAGER:
            return
        # Start only for runserver:
        # - default autoreload: run in child process (RUN_MAIN=true)
        # - --noreload mode: run in the single process (RUN_MAIN missing)
        is_runserver = any(arg == 'runserver' or arg.startswith('runserver') for arg in sys.argv)
        if not is_runserver:
            return
        run_main = os.environ.get('RUN_MAIN', '').lower()
        no_reload = '--noreload' in sys.argv
        if not no_reload and run_main != 'true':
            return

        global _dev_scheduler_started
        with _dev_scheduler_lock:
            if _dev_scheduler_started:
                return
            _dev_scheduler_started = True

        try:
            # Import task callables on the main thread so the scheduler thread
            # does not race Django startup imports.
            from .tasks import poll_gmail_for_replies, process_active_leads_once
        except Exception as exc:
            logger.exception(f"[DevScheduler] failed to initialize: {exc}")
            with _dev_scheduler_lock:
                _dev_scheduler_started = False
            return

        def _runner():
            from django.db import close_old_connections

            tick = 0
            while True:
                try:
                    close_old_connections()
                    processed = process_active_leads_once()
                    if processed:
                        logger.info(f"[DevScheduler] processed campaign leads: {processed}")
                    if tick % 4 == 0:
                        poll_gmail_for_replies()
                except Exception as exc:
                    logger.exception(f"[DevScheduler] loop error: {exc}")
                finally:
                    close_old_connections()
                tick += 1
                time.sleep(15)

        thread = threading.Thread(target=_runner, name='campaign-dev-scheduler', daemon=True)
        thread.start()
        logger.warning("[DevScheduler] started (15s processing loop, 1m reply polling)")
