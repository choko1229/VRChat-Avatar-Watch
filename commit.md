# Branch: main

**Purpose:** Primary development branch

_Commits will be appended below._

## Commit 6a53b1ae — 2026-07-12 15:24 UTC

### Branch Purpose
Primary development branch

### Previous Progress Summary


### This Commit's Contribution
Verified production via browser: Discord OAuth login, admin dashboard, crawl logs. Found real IntegrityError/deadlock errors from concurrent crawl writes (admin-triggered background threads vs scheduled worker). Fixed with a process-wide threading.Lock serializing crawl_target writes plus a missing db.rollback() in the exception handler. Tests pass (50), pushed as 46b08ba and c3cfc46. Remaining items need Pterodactyl SSH/console access or the user's own actions (booth_ops_check.py --save, Discord webhook/Misskey real send, restart persistence).

---

