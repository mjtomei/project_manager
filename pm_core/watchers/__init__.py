"""Built-in watcher implementations.

Each watcher is a ``BaseWatcher`` subclass registered in
``WATCHER_REGISTRY`` so the ``WatcherManager`` and CLI can
discover them by type name.
"""

from pm_core.watchers.auto_start_watcher import AutoStartWatcher
from pm_core.watchers.bug_fix_impl_watcher import BugFixImplWatcher
from pm_core.watchers.discovery_supervisor import DiscoverySupervisorWatcher
from pm_core.watchers.improvement_fix_impl_watcher import ImprovementFixImplWatcher
from pm_core.watchers.session_health_watcher import SessionHealthWatcher

# Registry mapping watcher type name -> class
WATCHER_REGISTRY: dict[str, type] = {
    AutoStartWatcher.WATCHER_TYPE: AutoStartWatcher,
    BugFixImplWatcher.WATCHER_TYPE: BugFixImplWatcher,
    DiscoverySupervisorWatcher.WATCHER_TYPE: DiscoverySupervisorWatcher,
    ImprovementFixImplWatcher.WATCHER_TYPE: ImprovementFixImplWatcher,
    SessionHealthWatcher.WATCHER_TYPE: SessionHealthWatcher,
}


def get_watcher_class(watcher_type: str) -> type | None:
    """Look up a watcher class by type name."""
    return WATCHER_REGISTRY.get(watcher_type)


def list_watcher_types() -> list[dict]:
    """List all registered watcher types with display info."""
    return [
        {
            "type": cls.WATCHER_TYPE,
            "display_name": cls.DISPLAY_NAME,
            "window_name": cls.WINDOW_NAME,
            "default_interval": cls.DEFAULT_INTERVAL,
        }
        for cls in WATCHER_REGISTRY.values()
    ]
