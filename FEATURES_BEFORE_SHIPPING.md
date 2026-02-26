# Features to Implement Before Shipping

This file tracks security and feature improvements that should be implemented before deploying to production.

---

## 1. Password Security Rules

**Current State:** Passwords only require minimum 6 characters.

**Required Improvements:**
- Minimum 8 characters (preferably 12)
- At least one uppercase letter
- At least one lowercase letter
- At least one number
- At least one special character (!@#$%^&* etc.)
- Check against common password lists (e.g., "password123", "admin", etc.)
- Show password strength indicator when typing

**Files to modify:**
- `services/auth_service.py` - add password validation function
- `routes/users.py` - use validation when creating/changing passwords
- `routes/user_auth.py` - use validation for password changes
- `templates/user_form.html` - add strength indicator
- `templates/user_password.html` - add strength indicator

---

## 2. Email Verification System

**Current State:** Users can register with any email without verification.

**Required Improvements:**
- When creating a user account, send verification email with unique code
- User must enter code (or click link) to verify email ownership
- Unverified accounts should have limited access
- Add "Resend verification email" option
- Set verification codes to expire after reasonable time (e.g., 24 hours)

**Implementation Steps:**
1. Add email configuration (SMTP server settings)
2. Add `email_verified` and `verification_code` columns to users table
3. Create email sending service
4. Create verification endpoint
5. Update user creation flow to require verification

**Files to create/modify:**
- `services/email_service.py` - new file for sending emails
- `database.py` - add new columns to users table
- `routes/user_auth.py` - add verification endpoints
- `templates/verify_email.html` - new template
- Create environment variables for SMTP configuration

---

## 3. Account Lockout After Failed Logins

**Current State:** Unlimited login attempts allowed.

**Should Add:**
- Lock account after 5 failed login attempts
- Lockout duration: 15-30 minutes
- Notify admin of locked accounts
- Track failed attempts by IP address as well

---

## Priority Order

1. Password Security Rules (High priority - easy to exploit)
2. Email Verification System (Medium priority)
3. Account Lockout (Medium priority)

---

*Last updated: January 2026*
