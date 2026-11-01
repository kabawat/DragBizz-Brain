---
module: staff
feature: management
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Staff & Roles

## Overview

Invite team members and control exactly what they can do at **Management → Staff** (`/dashboard/management/staff`, Team tab). Each staff member gets a role title and a **permission matrix** — per module (billing, invoice, product, inventory, supplier, customer, expense, purchase order, sales order, reports) you grant Create / View / Edit / Delete / Reports / Analytics. Staff need a paid plan: Basic allows 2 staff, Standard 5, Premium unlimited (free plans: none).

## Workflow

1. **Invite Staff** — enter Name, Email, and Role Title; assign one or more stores; set permissions manually or start from a preset (**Manager**, **Cashier**, **Inventory Staff**).
2. The person receives an **email invitation** (valid **48 hours**). Opening the link activates their account and signs them in; on first login they must set a password.
3. Pending invites show an "Invitation Pending" banner with expiry — you can **Resend** or **Cancel Invitation**.
4. **Edit Permissions** anytime from the staff card; changes apply on their next request.
5. **Remove Staff** permanently deletes their access and login.

## What staff see

- The sidebar/pages are filtered by their permissions; the dashboard home becomes an "Operations Overview" of permitted module tiles.
- In Settings they only get Appearance, Language, and Profile.
- Staff can never access Management pages (staff, subscription, limits), store settings, or billing — those are owner-only.

## Business rules

- Staff log in with the same login page as owners, using their own email and password.
- An email that already has a DragBizz account **cannot be invited** ("User with this email already exists in the system. Cannot invite existing user.").
- The `staff`/`store` modules can't be delegated — only the owner manages team, stores, attendance, and salary.
- Invites count against the plan's staff limit; on free plans inviting is blocked with an upgrade message.
- Removing a staff member is permanent (their invoices/entries remain, attributed to them). There is no temporary "deactivate" switch in the app today.
- Permission checks return precise errors, e.g. "Access denied. You do not have 'create' permission for invoice."

## Examples

- "Cashier ko sirf billing dena hai" → Invite → preset Cashier → invoice/billing create+view only.
- "Manager sab dekh sake par delete na kare" → grant View/Create/Edit across modules, leave Delete off.
- "Invite expire ho gaya" → staff card → Resend.

## Errors

- "This feature (staff) is not available in your current plan." / staff quota reached — upgrade needed.
- "Please fill all fields…" / "At least one store…" — invite form incomplete.
- "User with this email already exists in the system. Cannot invite existing user."
- "Access denied. Your staff account is inactive or not found." — the staff member was removed.

## FAQ

**Q: Can a staff member see my revenue/profit?** 
Only if you grant them Reports/Analytics permissions; the owner dashboard metrics are never shown to staff.

**Q: What if the invite email doesn't arrive?** 
Use Resend from the staff card; check spam. Invites expire after 48 hours.

**Q: Can I make someone a co-owner?** 
No — there is one owner; staff permissions can be broad but Management/billing stays with the owner.
