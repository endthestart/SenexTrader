# CSRF Token Pattern - Developer Reference

## Established Pattern (DO THIS ✅)

### In JavaScript (All Templates)

```javascript
// Use the centralized getCsrfToken() function from utils.js
fetch('/api/endpoint/', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()  // ✅ CORRECT
    },
    body: JSON.stringify(data)
})
```

### The getCsrfToken() Function

**Location**: `/static/js/utils.js` (lines 54-64)

```javascript
function getCsrfToken() {
    const name = 'csrftoken';
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [key, value] = cookie.trim().split('=');
        if (key === name) {
            return decodeURIComponent(value);
        }
    }
    return '';
}
```

**Global Export**: Available as `window.getCsrfToken` in all templates

### In Django Views

```python
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods

@login_required
@require_http_methods(["POST"])
async def my_api_view(request):
    # CSRF protection handled by Django middleware automatically
    # No decorator needed unless middleware is disabled
    ...
```

### For API Endpoints That Return Cookies

```python
from django.views.decorators.csrf import ensure_csrf_cookie

@ensure_csrf_cookie  # ✅ Ensures CSRF cookie is set for AJAX
@login_required
def my_api_view(request):
    return JsonResponse({"status": "ok"})
```

## Anti-Patterns (DON'T DO THIS ❌)

### ❌ Using Django Template Variables

```javascript
// WRONG - Don't inject Django template variables into JavaScript
fetch('/api/endpoint/', {
    headers: {
        'X-CSRFToken': '{{ csrf_token }}'  // ❌ WRONG
    }
})
```

**Why?**: Tight coupling between Django templates and JavaScript, harder to maintain

### ❌ Reimplementing getCsrfToken()

```javascript
// WRONG - Don't reimplement the function in every template
function getCsrfToken() {  // ❌ DUPLICATE CODE
    return document.cookie.split('; ')
        .find(row => row.startsWith('csrftoken='))
        ?.split('=')[1] || '';
}
```

**Why?**: Violates DRY principle, creates inconsistency

### ❌ Reading from DOM Elements

```javascript
// WRONG - Don't read from hidden form fields
const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;  // ❌
```

**Why?**: Requires hidden form field in every template, brittle

### ❌ Unnecessary Decorators

```python
from django.views.decorators.csrf import csrf_protect

@csrf_protect  # ❌ UNNECESSARY - middleware already does this
@login_required
def my_view(request):
    ...
```

**Why?**: Django's CSRF middleware already protects all POST requests

## When to Use Specific Decorators

### @ensure_csrf_cookie
**Use when**: Your view serves a page/API that will make AJAX POST requests

```python
@ensure_csrf_cookie  # ✅ Good for initial page loads
@login_required
def trading_page(request):
    return render(request, 'trading/trading.html')
```

### @csrf_exempt
**Use when**: You need to exempt a specific view from CSRF protection (rare, security risk!)

```python
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt  # ⚠️ SECURITY RISK - Only for external webhooks
def webhook_endpoint(request):
    # Validate webhook signature instead
    ...
```

## Testing CSRF Protection

### Manual Testing
1. Open browser DevTools → Network tab
2. Check request headers for `X-CSRFToken`
3. Verify cookie `csrftoken` is set
4. Attempt POST without token → should get 403 Forbidden

### Automated Testing
```python
def test_csrf_protection(self):
    response = self.client.post('/api/endpoint/', {})
    self.assertEqual(response.status_code, 403)  # CSRF failure
    
    # With CSRF token
    self.client.get('/page/')  # Get CSRF cookie
    response = self.client.post('/api/endpoint/', {})
    self.assertEqual(response.status_code, 200)  # Success
```

## Summary

✅ **DO**: Use `getCsrfToken()` from `utils.js` everywhere  
✅ **DO**: Let Django middleware handle CSRF protection  
✅ **DO**: Use `@ensure_csrf_cookie` for initial page loads  
❌ **DON'T**: Inject Django template variables into JavaScript  
❌ **DON'T**: Reimplement getCsrfToken() in templates  
❌ **DON'T**: Use `@csrf_protect` unless middleware is disabled  

---

**Last Updated**: 2025-11-08  
**Related Files**: 
- `/static/js/utils.js` (centralized function)
- `/templates/base/base.html` (includes utils.js)
- `/trading/api_views.py` (API endpoint examples)
