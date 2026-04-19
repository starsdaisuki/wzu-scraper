# Security Policy

## What NOT to commit

- `.env` files (contains credentials)
- `.cookies.json` (contains session tokens)
- `*.har` files (contains full HTTP request/response including auth data)
- Screenshots with login pages or personal info
- Any file containing real student IDs, passwords, or session tokens

All of these are already in `.gitignore`.

## Responsible Use

This project is for **personal learning and research only**. Please:

- Don't use it to access other people's accounts
- Don't send high-frequency requests to school servers
- Don't use the technical analysis to attack school systems
- Your credentials stay local — nothing is sent anywhere except `*.wzu.edu.cn`

## Reporting Issues

If you find a security issue in this project, open a GitHub issue.
For security issues in WZU's systems, contact the school's IT department.
