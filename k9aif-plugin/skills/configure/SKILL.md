---
description: Configure the K9-AIF plugin context for this session. Must be run before any other k9aif skill. Sets the project root and active app name used by all subsequent commands.
---

# K9-AIF: Configure

Set up the K9-AIF plugin context for this session. This must be run before any other `/k9aif:` skill.

## What to do

Ask the user the following two questions (one at a time):

1. **Project root** — the absolute path to the k9-aif-framework repository.
   > "What is your project root? (e.g. `/Users/yourname/ai/k9-aif-framework`)"
   - Verify the path exists and contains `k9_aif_abb/` — if not, tell the user it doesn't look like a K9-AIF project and ask again.

2. **App name** — the name of the app to work on.
   > "Which app are you working on?"
   - List the existing folders under `examples/` and `k9_projects/` so the user can pick one.
   - Or the user can type a new name to create a new app.
   - If a new name is given, confirm: "App `<name>` does not exist yet. Create it under `examples/<name>/`?"

## On success

Confirm with:
> "K9-AIF context configured.
> Project: <project_root>
> App: <app_name> → <project_root>/examples/<app_name>/
>
> You can now use:
> /k9aif:add-agent, /k9aif:add-squad, /k9aif:add-validation-loop, /k9aif:add-router, /k9aif:add-adapter, /k9aif:inspect"

Store the confirmed values as:
- `K9AIF_PROJECT_ROOT` = the absolute project path
- `K9AIF_APP_NAME` = the app name

## Re-running configure

If configure has already been run, show the current context and ask:
> "Current context — Project: <root>, App: <app>. Do you want to change it?"
