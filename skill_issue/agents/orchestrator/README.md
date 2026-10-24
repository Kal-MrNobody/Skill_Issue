![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# SkillAudit

Check an AI agent skill before you install it. Send a link to a GitHub repository that
contains a `SKILL.md`, and SkillAudit tells you whether the skill can be trusted.

## What it does
1. Pins the repository to an exact commit and downloads it safely (no clone, no execution).
2. Finds every `SKILL.md`; if there are several, asks you which one to audit.
3. Runs a static security scan (cisco-ai-skill-scanner) and sorts findings into prompt
   injection, dangerous commands, network use and install/persistence, each with file:line.
4. Replies with a report card: a trust verdict, the findings, and undeclared network domains.

No letter grades and no composite score. This version reports security only: it never
runs the skill, so it does not claim whether the skill helps.

## Example prompts
- Audit this skill: https://github.com/anthropics/skills
- Is https://github.com/owner/repo/tree/main/skills/pdf safe to install?

## Inputs / outputs
- Input: a public GitHub URL (repo, or `/tree/<ref>/<path>` to one skill).
- Output: an ASI:One card (skill picker, then report) with a plain-text summary.

## Keywords
skill audit, agent skill, SKILL.md, security scan, prompt injection, supply chain, Claude skills
