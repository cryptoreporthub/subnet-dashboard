# .restless/

Created by `npx restless init`. **Commit this directory along with your code.**

It is configuration, not a build artifact or a cache. Do not add it to
`.gitignore`, and include it in commits that change it.

| file | what it is |
| ---- | ---------- |
| `settings.json` | Which APIs live in this repo, where their specs are, and the redaction rules the SDK applies. Read by `@restlessai/sdk` at startup. |
| `openapi.json` | The OpenAPI spec describing your API. Regenerate with `npx restless init`. |

No credentials are stored here. Your `RESTLESS_KEY` belongs in `.env`
(or wherever you keep secrets), which should stay out of git.
