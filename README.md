# AutoPR Reviewer 🤖

> AI-powered code review on every pull request — automatically, the moment it's opened.

AutoPR Reviewer catches bugs, security issues, style violations, and performance problems before your team has to. No setup. No config. Just install and ship.

---

## See It In Action

<!-- Replace the paths below with your actual screenshots -->
![AutoPR Review Example](https://github.com/user-attachments/assets/8bdf4440-41af-4bcf-916a-25e5d30807b5)
![AutoPR Security & Static Analysis](https://github.com/user-attachments/assets/4bd6c7e5-1641-458d-9a15-e32500c59fbb)

---

## Install in One Click

[![Install AutoPR Reviewer](https://img.shields.io/badge/Install%20on%20GitHub-AutoPR%20Reviewer-2ea44f?style=for-the-badge&logo=github)](https://github.com/apps/autopr-reviewer)

No configuration required. Install the app on any repo and AutoPR starts reviewing your next PR automatically.

---

## What You Get

Every pull request gets a structured review comment with:

- 📋 **PR Summary** — what changed and why it matters
- 🔴 **Risk Score** — LOW / MEDIUM / HIGH based on file count, change volume, and sensitive files
- 🐛 **Potential Bugs** — logic errors and edge cases flagged per file
- 🔒 **Security Concerns** — authentication gaps, exposed endpoints, and unsafe patterns
- ⚡ **Performance Suggestions** — inefficient patterns and caching opportunities
- 🎨 **Style Issues** — formatting and readability problems
- 🔍 **Static Analysis** — flake8 findings with exact line numbers

---

## Plans

| Feature | Free | Pro ($5/mo) |
|---|---|---|
| AI-powered code review | ✅ | ✅ |
| Bug, style & performance detection | ✅ | ✅ |
| Risk scoring | ✅ | ✅ |
| Static analysis (flake8) | ✅ | ✅ |
| PR complexity score & estimated review time | ❌ | ✅ |
| Security pattern detection (hardcoded secrets, SQL injection, eval/exec) | ❌ | ✅ |
| Large function detection (>50 lines) | ❌ | ✅ |
| Deeply nested loop detection (>3 levels) | ❌ | ✅ |
| Missing error handling detection | ❌ | ✅ |

Upgrade to Pro from your AutoPR dashboard.

---

## How It Works

1. You open or update a pull request
2. AutoPR receives the event instantly
3. Static analysis and AI review run in parallel
4. A full review comment is posted on your PR — usually within seconds

---

## FAQ

**Does this work on private repos?**
Yes. AutoPR works on both public and private repositories.

**What languages does it support?**
AutoPR works on any language for AI review. Static analysis (flake8) applies to Python files.

**Is my code sent anywhere?**
Only the PR diff is processed. Your full codebase is never cloned or stored.

**How do I upgrade to Pro?**
Log in with GitHub at [your dashboard URL] and go to the billing section.

---

[![Made with Supabase](https://supabase.com/badge-made-with-supabase-dark.svg)](https://supabase.com)
