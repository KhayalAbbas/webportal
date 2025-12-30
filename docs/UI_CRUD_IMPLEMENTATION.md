# ATS UI Create/Edit Flows - Implementation Summary

## Completed ✅

### 1. Candidates - Create & Edit
**Files Created/Modified:**
- `app/ui/templates/candidate_form.html` - Form template for create/edit
- `app/ui/routes/candidates.py` - Added routes:
  - `GET /ui/candidates/new` - Show create form
  - `POST /ui/candidates/new` - Handle create
  - `GET /ui/candidates/{id}/edit` - Show edit form
  - `POST /ui/candidates/{id}/edit` - Handle update
- `app/ui/templates/candidates_list.html` - Added "+ Add Candidate" button
- `app/ui/templates/candidate_detail.html` - Added "Edit Candidate" button and success message display

**Access Control:** admin, consultant only

**Form Fields:** All candidate fields including contact info, personal details, career info, scores, and profile

**Success Messages:** Implemented via query parameter `?msg=...`

### 2. Companies - Create & Edit
**Files Created/Modified:**
- `app/ui/templates/company_form.html` - Form template for create/edit
- `app/ui/routes/companies.py` - Added routes:
  - `GET /ui/companies/new` - Show create form
  - `POST /ui/companies/new` - Handle create
  - `GET /ui/companies/{id}/edit` - Show edit form
  - `POST /ui/companies/{id}/edit` - Handle update
- `app/ui/templates/companies_list.html` - Added "+ Add Company" button
- `app/ui/templates/company_detail.html` - Added "Edit Company" button and success message display

**Access Control:** admin, consultant, bd_manager

**Form Fields:** name, industry, headquarters_location, website, notes, BD fields (status, owner, last_contacted, is_client, is_prospect)

## Remaining To Implement 📝

### 3. Roles - Create & Edit + Pipeline Actions

**Templates to Create:**
```html
<!-- app/ui/templates/role_form.html -->
Similar structure to candidate_form.html with fields:
- title*
- company_id (dropdown populated from companies)
- function
- location  
- status (dropdown: open/on_hold/closed)
- seniority_level
- description (textarea)
```

**Routes to Add in `app/ui/routes/roles.py`:**
```python
# Add imports:
from fastapi import Form
from app.core.permissions import raise_if_not_roles, Roles
from app.schemas.role import RoleCreate, RoleUpdate
from app.repositories.role_repository import RoleRepository

# Routes:
GET /ui/roles/new
POST /ui/roles/new  
GET /ui/roles/{role_id}/edit
POST /ui/roles/{role_id}/edit
POST /ui/roles/{role_id}/pipeline  # For updating candidate pipeline
```

**Pipeline Actions on Role Detail:**
Add to `role_detail.html` - for each candidate in pipeline table, add a small form:
```html
<form method="POST" action="/ui/roles/{{ role.id }}/pipeline" style="display: inline;">
    <input type="hidden" name="assignment_id" value="{{ assignment.id }}">
    <select name="assignment_status">
        <option value="ACTIVE" {% if assignment.assignment_status == 'ACTIVE' %}selected{% endif %}>Active</option>
        <option value="PRESENTED" ...>Presented</option>
        <!-- etc -->
    </select>
    <label><input type="checkbox" name="is_hot" {% if assignment.is_hot %}checked{% endif %}> Hot</label>
    <button type="submit" class="btn btn-small">Save</button>
</form>
```

**Access:** admin, consultant

### 4. Contacts - Create & Edit

**Templates:**
```html
<!-- app/ui/templates/contact_form.html -->
Fields:
- first_name*, last_name*
- email, phone
- role/title
- bd_status, bd_owner
- date_of_birth, work_anniversary_date
- company_id (hidden when creating from company page)
```

**Routes in `app/ui/routes/companies.py` or new `contacts.py`:**
```python
GET /ui/companies/{company_id}/contacts/new
POST /ui/companies/{company_id}/contacts/new
GET /ui/contacts/{contact_id}/edit
POST /ui/contacts/{contact_id}/edit
```

**Company Detail Updates:**
- Add "+ Add Contact" button in contacts section

**Access:** admin, consultant, bd_manager

### 5. BD Opportunities - Create & Edit

**Templates:**
```html
<!-- app/ui/templates/bd_opportunity_form.html -->
Fields:
- company_id (dropdown)
- contact_id (optional dropdown)
- title
- status (dropdown: PROSPECTING/PROPOSAL/WON/LOST)
- stage
- estimated_value, currency, probability
- notes
- lost_reason, lost_reason_detail (show if status=LOST)
```

**Routes in `app/ui/routes/bd_opportunities.py`:**
```python
GET /ui/bd-opportunities/new
POST /ui/bd-opportunities/new
GET /ui/bd-opportunities/{id}/edit
POST /ui/bd-opportunities/{id}/edit
```

**List/Detail Updates:**
- Add "+ Add BD Opportunity" button on list page
- Add "Edit" button on detail page
- Also add "+ Add BD Opportunity" on company_detail.html

**Access:** admin, bd_manager

### 6. Tasks - Edit & Status Update

**Templates:**
```html
<!-- app/ui/templates/task_form.html -->
Fields:
- title*, description
- due_date, status
- related_entity_type, related_entity_id
- assigned_to_user (if implementing)
```

**Routes in `app/ui/routes/tasks.py`:**
```python
# Already has create, add:
GET /ui/tasks/{task_id}/edit
POST /ui/tasks/{task_id}/edit
```

**Tasks List Updates:**
- Add "Edit" link per row

**Access:** admin, consultant, bd_manager

### 7. Lists - Rename & Remove Items

**Routes in `app/ui/routes/lists.py`:**
```python
# Rename list
GET /ui/lists/{list_id}/edit
POST /ui/lists/{list_id}/edit

# Remove candidate from list  
POST /ui/lists/{list_id}/items/{item_id}/delete
```

**List Detail Updates:**
- Add "Edit List" button at top
- Add "Remove" button/link for each candidate row

**Access:** admin, consultant

### 8. Flash Messages System

**Already Partially Implemented:**
- Base template has `.alert-success` and `.alert-error` styles
- Candidate and Company routes use `?msg=...` query parameter
- Templates check for `success_message` variable

**To Complete:**
Apply same pattern to all other routes (roles, contacts, BD opps, tasks, lists)

## Implementation Pattern

All create/edit flows follow this pattern:

### GET (new/edit):
```python
@router.get("/ui/entity/new")
async def new_entity_page(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
):
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.CONSULTANT], "create entity")
    return templates.TemplateResponse("entity_form.html", {
        "request": request,
        "current_user": current_user,
        "mode": "create",
        "entity": None,
    })
```

### POST (create):
```python
@router.post("/ui/entity/new")
async def create_entity(
    request: Request,
    field1: str = Form(...),
    field2: Optional[str] = Form(None),
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db),
):
    raise_if_not_roles(current_user.role, [Roles.ADMIN, Roles.CONSULTANT], "create entity")
    try:
        entity_data = EntityCreate(tenant_id=current_user.tenant_id, field1=field1, field2=field2)
        repo = EntityRepository(db)
        entity = await repo.create(entity_data)
        await db.commit()
        return RedirectResponse(
            url=f"/ui/entity/{entity.id}?msg=Entity+created+successfully",
            status_code=303
        )
    except Exception as e:
        return templates.TemplateResponse("entity_form.html", {
            "request": request,
            "current_user": current_user,
            "mode": "create",
            "entity": None,
            "error": f"Error: {str(e)}"
        })
```

### Template Structure:
```html
{% extends "base.html" %}
{% block content %}
<h1>{{ 'Edit' if mode == 'edit' else 'Create' }} Entity</h1>

{% if error %}
<div class="alert alert-error">{{ error }}</div>
{% endif %}

<form method="POST">
    <!-- fields -->
    <button type="submit">{{ 'Update' if mode == 'edit' else 'Create' }}</button>
    <a href="{{ back_url }}" class="btn btn-secondary">Cancel</a>
</form>
{% endblock %}
```

### Detail Page Success Message:
```html
{% if success_message %}
<div class="alert alert-success">{{ success_message }}</div>
{% endif %}
```

And in the route:
```python
msg = request.query_params.get("msg", "")
# ... add to template context:
"success_message": msg,
```

## Role-Based Access Summary

| Action | Admin | Consultant | BD Manager | Viewer |
|--------|-------|------------|------------|--------|
| Create/Edit Candidates | ✓ | ✓ | ✗ | ✗ |
| Create/Edit Companies | ✓ | ✓ | ✓ | ✗ |
| Create/Edit Roles | ✓ | ✓ | ✗ | ✗ |
| Update Role Pipeline | ✓ | ✓ | ✗ | ✗ |
| Create/Edit Contacts | ✓ | ✓ | ✓ | ✗ |
| Create/Edit BD Opps | ✓ | ✗ | ✓ | ✗ |
| Create/Edit Tasks | ✓ | ✓ | ✓ | ✗ |
| Create/Edit Lists | ✓ | ✓ | ✗ | ✗ |

## Example Workflow

**End-to-end candidate search:**

1. Login as admin/consultant
2. Companies → "+ Add Company" → Fill form → Save
3. Company Detail → "+ Add Contact" → Fill form → Save  
4. Company Detail → "Add Role" → Fill form → Save
5. Candidates → "+ Add Candidate" → Fill form → Save
6. Role Detail → "Add to Pipeline" (existing) → Select candidate
7. Role Detail → Update pipeline status/is_hot per candidate → Save
8. Tasks → "+ Add Task" → Link to candidate/role → Save
9. Lists → Create shortlist → Add candidates

## Testing Checklist

- [ ] All create forms load without errors
- [ ] All edit forms load with prepopulated data
- [ ] Success messages appear after create/edit
- [ ] Redirects work correctly (Post/Redirect/Get)
- [ ] Permission checks block viewer from editing
- [ ] Date fields parse correctly
- [ ] Checkboxes work (is_client, is_prospect, is_hot)
- [ ] Dropdowns populated (companies for roles, statuses, etc.)
- [ ] Cancel buttons return to correct page
- [ ] Pipeline updates work on role detail
- [ ] Contact create from company page sets company_id
- [ ] BD Opp can be created from company page
- [ ] List item removal works
- [ ] List rename works
