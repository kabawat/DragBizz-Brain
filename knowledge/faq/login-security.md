---
module: faq
feature: login-security
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Login, Sessions & Password Reset

## Overview

Sign in with your **email or phone** using either your **password** or a one-time **OTP** (phone logins default to OTP). Sessions last about 30 days per device with automatic refresh. Forgot password is a three-step OTP flow from the login page.

## Login

- Enter email or phone (auto-detected) → choose Password or OTP.
- OTP login: a 5-digit code arrives (10-minute validity, 60-second resend); up to 10 attempts before a 15-minute lock.
- Staff members log in the same way with their own credentials (their first login after accepting an invite forces a password setup).

## Sessions

- Each device gets its own session (~30 days); short-lived tokens refresh automatically in the background.
- Logout ends only the current device's session; other devices stay signed in.
- Changing or resetting your password signs out **all** devices ("Session expired or access token revoked. Please login again.").

## Password reset

1. Login page → **Forgot password** → enter email/phone.
2. Receive the reset OTP (valid 10 minutes; 60-second resend; daily limit applies).
3. Verify the code → set the new password (minimum 8 characters with a letter and a number) → "Password has been reset successfully. Please login with your new password."

## Errors

- "Invalid credentials." — wrong password.
- "Account does not exist. Please register first."
- "If the account exists, a password reset code has been sent." — shown regardless, for security.
- "Too many attempts. Please try again later." / "Daily limit exceeded. Please try again tomorrow."
- "Please wait N minute(s) before requesting a new OTP."

## FAQ

**Q: Password change karne ke baad doosre device se logout kyun ho gaya?** 
By design — any password change/reset invalidates all sessions for safety.

**Q: Is there two-factor authentication?** 
Not yet — OTP login is available as an alternative to passwords.

**Q: Can I change my login email/phone?** 
Not from the app currently — contact support.
