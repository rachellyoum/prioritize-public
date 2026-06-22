# This file pre-imports user_service.api WITHOUT executing the NiceGUI admin UI.

# Temporarily disable NiceGUI's ui.run_with so importing user_service.api
# does NOT attempt to add middleware after app startup.

_original_run_with = None

try:
    from nicegui import ui

    if hasattr(ui, "run_with"):
        _original_run_with = ui.run_with
        ui.run_with = lambda *args, **kwargs: None

    # NOW import user_service.api safely

finally:
    # Restore original ui.run_with so admin works normally later
    if _original_run_with is not None:
        from nicegui import ui
        ui.run_with = _original_run_with
