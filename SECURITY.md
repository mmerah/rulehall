# Security policy

Thanks for taking the time to look. Rulehall is a hobby project that I maintain on my own, but I take security reports seriously and I'd much rather hear about a problem from you than find it the hard way.

## Supported versions

There are no releases yet. I fix issues on `master`, and the fix ships in the next `ghcr.io/mmerah/rulehall:latest` image. If you run an older commit or image, please update first and check the issue is still there.

## Reporting a vulnerability

Please don't open a public issue. Use GitHub's private reporting instead: [report a vulnerability](https://github.com/mmerah/rulehall/security/advisories/new).

A good report tells me what goes wrong, how to reproduce it, and which commit or image tag you used. A proof of concept helps, but a clear description is fine too.

I'll reply within a week, usually sooner. Once I can reproduce it, I'll keep you posted on the fix, and I'll credit you in the advisory unless you'd rather stay anonymous.

## What I care about most

- A save, scenario, pack or uploaded PDF that gets the app to run code, or to read or write files outside its data folders.
- Prompt injection that gets one of the AI roles to use a tool or a command it was never given.
- Any way to read a stored API key back out of the page or the logs.
- Anything in the Docker image an attacker can actually reach.

## Known limits, by design

- The app has no login. Anyone who can reach the port can play and change every setting. That's fine on your own machine or a private Tailscale network, but please never expose it to the open internet.
- What your AI provider charges you or writes back is between you and that provider.
