# config

Framework default configuration. A solution's own `config/config.yaml` overrides these.

- `config.yaml`: infrastructure and runtime settings (inference and model catalog, persistence,
  messaging, logging, monitoring, `security.shield` (off here; solutions enable it)).
- `flows.yaml`, `flows_llm.yaml`: agent step lists for the default flows.
- `orchestrators.yaml`: orchestrators registered by `name`, `module` and `intent`.
- `governance.yaml`: governance policy settings.
- `tools.yaml`: tool definitions.
- `example_squads.yaml`: sample squad definitions.
