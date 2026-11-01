---
module: settings
feature: account
version: 1
language: en
updated_at: 2026-07-25
status: partial
---


# Profile & Security

## Overview

Personal settings live in **Settings** (`/dashboard/settings`): Appearance, Language, Profile, and Security (password). These are the only Settings tabs staff members can see; owners additionally get Store, Signatures, Invoice Number, Notifications, and Account tabs. Appearance and Language have dedicated knowledge docs.

## Appearance (summary)

Full accent-theme catalog lives in the Appearance knowledge doc. Short facts only:

- **Interface mode:** Light or Dark (not the same as color themes).
- **Accent color themes:** **5 types/categories** (Warm, Cool, Green, Vibrant, Neutral) with **22** named themes (Default, Ocean, Violet, Emerald, Amber, Slate, etc.).
- Reset to Defaults → Default accent + Light mode. Saved per device/browser.

For "kitne color themes / theme types" questions, answer with the 5 categories and 22 themes — do **not** answer only Light/Dark.

## Language (summary)

Full how-to lives in the Language knowledge doc. Short facts only:

- **4 options:** English, हिंदी (Hindi), ગુજરાતી (Gujarati), Hinglish.
- Change at **Settings → Language** — click a language card; applies immediately (no restart).
- Per device/user; also drives the voice assistant speech language.

For "language change kaise kare / kitni languages" questions, use the Language doc steps — never refuse language settings help.

## Profile

- Shows full name, email, phone, date of birth, gender, and profile photo.
- Editable: first/last name, DOB, gender, and profile picture (upload). **Email and phone cannot be changed** from the profile.

## Security (password)

- **Change password**: enter current password, then the new one twice (minimum 8 characters, must contain a letter and a number).
- 3 wrong current-password attempts lock the change for 10 minutes — use Forgot Password instead.
- **Forgot password** (from the login page): enter email/phone → receive an OTP (valid 10 minutes) → verify → set a new password.
- Changing or resetting the password signs out all other sessions. Two-factor authentication is not available.
- Sessions: you stay signed in ~30 days per device; tokens refresh automatically.

## Business rules / known gaps

- The **Account** tab (timezone, date format, currency, auto-save preferences) currently **does not save** — those preferences are not persisted yet; only the language control there works. Documented as not-yet-functional.
- The "Change Password" and "Download Account Data" buttons on the Profile tab are placeholders — use the **Security** tab to change the password.

## Errors

- "Old password is incorrect" / "Too many failed attempts. Please use forgot password option."
- Password rules: minimum 8 characters with a letter and a number; "Passwords do not match".
- OTP: "Invalid verification code. X attempts remaining.", "Verification code has expired…", "Please wait N minute(s) before requesting a new OTP.", "Daily limit exceeded. Please try again tomorrow."

## FAQ

**Q: Can I change my login email or phone?** 
Not from the app currently — contact support.

**Q: My theme reset on another computer — why?** 
Theme is stored per device, not on your account. See Appearance docs for the full theme list.

**Q: Does language change affect my staff?** 
No — language is a per-user, per-device setting.
