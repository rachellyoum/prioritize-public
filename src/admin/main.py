from fastapi import Depends
from nicegui import ui, app
from sqlalchemy.exc import IntegrityError
import logging
import os

from user_service.models.user import UserRepository, get_user_repository, User
from user_service.schemas import UserSchema
from sqlalchemy import select
from shared.database import get_db
from task_service.models import Task
from scheduler_service.models import GeneratedSchedule


logger = logging.getLogger('uvicorn.error')

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "team13")

@ui.refreshable
async def user_list(user_repo: UserRepository, page: int = 1) -> None:
    """
    Display a table of 100 users per page with delete functionality.
    Args:
        user_repo: UserRepository for database operations
    """
    USERS_PER_PAGE = 100

    # Get total count and calculate pages
    total_users = user_repo.count_users()
    total_pages = (total_users + USERS_PER_PAGE - 1) // USERS_PER_PAGE

    # Get users for current page
    offset = (page - 1) * USERS_PER_PAGE
    user_models = user_repo.get_users_paginated(limit=USERS_PER_PAGE, offset=offset)

    users = []
    for model in user_models:
        users.append(UserSchema.from_db_model(model).model_dump())

    ui.label(f"All Users (Page {page} of {total_pages} - Showing {len(users)} of {total_users} total)")

    async def delete():
        """Delete selected users from the database."""
        global selected
        for user in selected:
            # Delete user by name (could be changed to delete_by_id)
            result = await user_repo.delete(user['name'])  
            if result.rowcount > 0:
                ui.notify(f"Deleted user '{user['name']}'")
            else:
                ui.notify(f"Unable to delete user '{user['name']}'")
        user_list.refresh() #instant user delete without having to refresh page

    # Create delete button (initially disabled)
    button = ui.button(on_click=delete, icon='delete')
    button.disable()

    def toggle_delete_button(e):
        """Enable delete button only when users are selected."""
        global selected
        selected = e.selection
        if len(e.selection) > 0:
            button.enable()
        else:
            button.disable()

    # Define table columns (id, name, email - password excluded for security)
    columns = [
    {'name': 'id', 'label': 'ID', 'field': 'id', 'required': True, 'align': 'left'},
    {'name': 'name', 'label': 'Name', 'field': 'name', 'required': True, 'align': 'left'},
    {'name': 'email', 'label': 'Email', 'field': 'email', 'required': True, 'align': 'left'}
]
    # Create table with multiple selection enabled
    table = ui.table(columns=columns, rows=users,
                     row_key='id', # Use id as unique identifier
                     on_select=toggle_delete_button)
    table.set_selection('multiple')

    with ui.row().classes('mt-4'):
        # Previous button
        if page > 1:
            ui.button('← Previous', on_click=lambda: user_list.refresh(user_repo, page - 1))

        # Page indicator
        ui.label(f'Page {page} of {total_pages}').classes('mx-4 self-center')

        # Next button
        if page < total_pages:
            ui.button('Next →', on_click=lambda: user_list.refresh(user_repo, page + 1))

@ui.page("/login")
async def login_page():
    """Login page for admin authentication."""
    def check_password():
        """Verify password and redirect to admin if correct."""
        if password_input.value == ADMIN_PASSWORD:
            app.storage.user['authenticated'] = True
            ui.navigate.to('/')
        else:
            ui.notify('Incorrect password', color='negative')
            password_input.value = ''
    
    with ui.column().classes('absolute-center items-center'):
        ui.label('Admin Login').classes('text-2xl mb-4')
        password_input = ui.input('Password', password=True, password_toggle_button=True) \
            .on('keydown.enter', check_password) \
            .classes('w-64')
        ui.button('Login', on_click=check_password)

@ui.page("/")
async def index(user_repo: UserRepository = Depends(get_user_repository)):
    """
    Main admin page for user management.
    
    Provides UI for:
    - Creating new users with name, email, and password
    - Viewing all users in a table
    - Deleting selected users
    
    Args:
        user_repo: UserRepository dependency injection
    """

    #check authentication
    if not app.storage.user.get('authenticated', False):
        ui.navigate.to('/login')
        return

    async def create() -> None:
        """Create a new user and refresh the user list."""

        # Clear input fields
        try:
            await user_repo.create(name=name.value, email=email.value, password=password.value)
        except IntegrityError:
            _sess = getattr(user_repo, "session", None) or getattr(user_repo, "db", None)
            if _sess is not None:
                _sess.rollback()
            ui.notify("User with this name or email already exists", color='negative')
            return
        
        name.value = ""
        email.value = ""
        password.value = ""

        user_list.refresh()

    def logout():
        """Clear authentication and redirect to login."""
        app.storage.user['authenticated'] = False
        ui.navigate.to('/login')

    with ui.column().classes('mx-auto'):
        # Add logout button at top
        with ui.row().classes('w-full justify-end gap-2'):
            ui.button('View Schedules', on_click=lambda: ui.navigate.to('/schedules'), icon='calendar_month')
            ui.button('Logout', on_click=logout, icon='logout')

        # Create input form with Tailwind CSS styling
        with ui.row().classes('w-full items-center px-4'):
            name = ui.input(label='Name')
            email = ui.input(label='Email')
            password = ui.input(label='Password', password=True, password_toggle_button=True)
            ui.button(on_click=create, icon='add')
        await user_list(user_repo)

@ui.page('/schedules')
def schedule_viewer():
    """
    Admin page to view schedules for specific users.
    """
    # Check auth
    if not app.storage.user.get('authenticated', False):
        ui.navigate.to('/login')
        return

    # Container for the schedule table (we refresh this container when user changes)
    schedule_container = ui.column().classes('w-full')

    def load_schedule(user_id):
        """Fetch schedule and refresh table."""
        schedule_container.clear()
        
        # Get a fresh DB session
        db = next(get_db()) 
        
        try:
            # Query Schedule joined with Task to get the Task Name
            stmt = (
                select(GeneratedSchedule, Task.name, Task.difficulty)
                .join(Task, Task.id == GeneratedSchedule.task_id)
                .where(GeneratedSchedule.user_id == user_id)
                .order_by(GeneratedSchedule.scheduled_start)
            )
            results = db.execute(stmt).all()
            
            if not results:
                with schedule_container:
                    ui.label('No schedule generated for this user yet.').classes('text-gray-500 italic')
                return

            # Format data for NiceGUI Table
            rows = []
            for sched, task_name, difficulty in results:
                rows.append({
                    'task': task_name,
                    'start': sched.scheduled_start.strftime('%a %H:%M'), # e.g. Mon 18:00
                    'end': sched.scheduled_end.strftime('%H:%M'),       # e.g. 20:00
                    'difficulty': difficulty,
                    'reason': sched.reasoning
                })

            with schedule_container:
                ui.table(
                    columns=[
                        {'name': 'task', 'label': 'Task', 'field': 'task', 'align': 'left', 'sortable': True},
                        {'name': 'start', 'label': 'Start', 'field': 'start', 'align': 'left'},
                        {'name': 'end', 'label': 'End', 'field': 'end', 'align': 'left'},
                        {'name': 'difficulty', 'label': 'Diff', 'field': 'difficulty', 'align': 'left'},
                        {'name': 'reason', 'label': 'AI Reasoning', 'field': 'reason', 'align': 'left'},
                    ],
                    rows=rows,
                    pagination=10
                ).classes('w-full')
                
        finally:
            db.close()

    # --- UI Layout ---
    with ui.column().classes('w-full p-4'):
        with ui.row().classes('items-center mb-4'):
            ui.button(icon='arrow_back', on_click=lambda: ui.navigate.to('/')).props('flat round')
            ui.label('Master Schedule Viewer').classes('text-2xl font-bold')
        
        # User Selector
        # We fetch all users to populate the dropdown
        db = next(get_db())
        try:
            users = db.execute(select(User)).scalars().all()
            # Create a dictionary for the dropdown: {1: "Bob (bob@test.com)", 2: ...}
            user_options = {u.id: f"{u.name} ({u.email})" for u in users}
        finally:
            db.close()

        ui.select(
            options=user_options, 
            label='Select Student', 
            on_change=lambda e: load_schedule(e.value)
        ).classes('w-96 mb-8')
        
        # The table goes here
        schedule_container