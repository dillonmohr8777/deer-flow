# DeerFlow Frontend

Like the original DeerFlow 1.0, we would love to give the community a minimalistic and easy-to-use web interface with a more modern and flexible architecture.

## Tech Stack

- **Framework**: [Next.js 16](https://nextjs.org/) with [App Router](https://nextjs.org/docs/app)
- **UI**: [React 19](https://react.dev/), [Tailwind CSS 4](https://tailwindcss.com/), [Shadcn UI](https://ui.shadcn.com/), [MagicUI](https://magicui.design/) and [React Bits](https://reactbits.dev/)
- **AI Integration**: [LangGraph SDK](https://www.npmjs.com/package/@langchain/langgraph-sdk) and [Vercel AI Elements](https://vercel.com/ai-sdk/ai-elements)

## Quick Start

### Prerequisites

- Node.js 22+
- pnpm 10.26.2+

### Installation

```bash
# Install dependencies
pnpm install

# Copy environment variables
cp .env.example .env
# Edit .env with your configuration
```

### Development

```bash
# Start development server
pnpm dev

# The app will be available at http://localhost:3000
```

### Build & Test

```bash
# Type check
pnpm typecheck

# Check formatting
pnpm format

# Apply formatting
pnpm format:write

# Lint
pnpm lint

# Run unit tests
pnpm test

# One-time setup: install Playwright Chromium browser
pnpm exec playwright install chromium

# Run E2E tests (builds and starts production server automatically)
pnpm test:e2e

# Build for production
pnpm build

# Start production server
pnpm start
```

## Site Map

```
├── /                    # Landing page
├── /chats               # Chat list
├── /chats/new           # New chat page
└── /chats/[thread_id]   # A specific chat page
```

## Configuration

### Environment Variables

Key environment variables (see `.env.example` for full list):

```bash
# Backend API URL (optional, uses local Next.js/nginx proxy by default)
NEXT_PUBLIC_BACKEND_BASE_URL="http://localhost:8001"
# LangGraph-compatible API URL (optional, uses local Next.js/nginx proxy by default)
NEXT_PUBLIC_LANGGRAPH_BASE_URL="http://localhost:8001/api"
```

## Project Structure

```
tests/
├── e2e/                    # E2E tests (Playwright, Chromium, mocked backend)
└── unit/                   # Unit tests (mirrors src/ layout)
src/
├── app/                    # Next.js App Router pages
│   ├── api/                # API routes
│   ├── showcase/           # Allowlisted public read-only demos
│   ├── workspace/          # Main workspace pages
│   └── mock/               # Mock/demo pages
├── components/             # React components
│   ├── ui/                 # Reusable UI components
│   ├── workspace/          # Workspace-specific components
│   ├── landing/            # Landing page components
│   └── ai-elements/        # AI-related UI elements
├── core/                   # Core business logic
│   ├── api/                # API client & data fetching
│   ├── artifacts/          # Artifact management
│   ├── config/              # App configuration
│   ├── i18n/               # Internationalization
│   ├── mcp/                # MCP integration
│   ├── messages/           # Message handling
│   ├── models/             # Data models & types
│   ├── settings/           # User settings
│   ├── skills/             # Skills system
│   ├── threads/            # Thread management
│   ├── todos/              # Todo system
│   └── utils/              # Utility functions
├── hooks/                  # Custom React hooks
├── lib/                    # Shared libraries & utilities
├── server/                 # Server-side code
│   └── better-auth/        # Authentication setup and session helpers
└── styles/                 # Global styles
```

## Scripts

| Command             | Description                           |
| ------------------- | ------------------------------------- |
| `pnpm dev`          | Start development server with Webpack |
| `pnpm build`        | Build for production                  |
| `pnpm start`        | Start production server               |
| `pnpm test`         | Run unit tests with Rstest            |
| `pnpm test:e2e`     | Run E2E tests with Playwright         |
| `pnpm format`       | Check formatting with Prettier        |
| `pnpm format:write` | Apply formatting with Prettier        |
| `pnpm lint`         | Run ESLint                            |
| `pnpm lint:fix`     | Fix ESLint issues                     |
| `pnpm typecheck`    | Run TypeScript type checking          |
| `pnpm check`        | Run both lint and typecheck           |

## Development Notes

- Uses pnpm workspaces (see `packageManager` in package.json)
- Webpack is the default development bundler until the upstream Turbopack PostCSS worker leak is fixed in a stable Next.js release (#5132). Set `DEER_FLOW_DEV_BUNDLER=turbo` to opt in to Turbopack for local diagnosis, or `DEER_FLOW_DEV_BUNDLER=webpack` to select Webpack explicitly. Reconsider the default after the stable fix is verified on macOS arm64 and Linux.
- Environment validation can be skipped with `SKIP_ENV_VALIDATION=1` (useful for Docker)
- Backend API URLs are optional; nginx proxy is used by default in development

## Workflow room

`/workspace/workflows` lists the Gateway's agency and personal workflow catalog.
The count, categories, input schemas, steps and acceptance checks come from the
catalog response; the UI does not start a runner for each definition. Search and
category filters help select a recipe, then the bounded schema form collects its
inputs. Synthetic examples are explicitly labeled and remain editable; loading
one never creates a run.

The status endpoint reports availability for LangGraph, CrewAI, Mastra,
DeepAgents, Agno and Inngest AgentKit. Unavailable frameworks cannot be selected
for execution. Browser-required recipes additionally require the guarded browser
capability. The room shows the actual shared running limit and queue capacity,
saved steps, worker/model/effort, evidence and usage. Missing billing stays
unavailable; unresolved usage is labeled as a known minimum. Resume applies only
to an interrupted saved run and preserves its remaining budget.

Requests use the existing authenticated CSRF fetcher. The actor header pins the
status read, and all catalog/run/action/artifact requests carry the server's
expected workflow scope. Cache keys include both actor and scope. Switching
account or scope aborts in-flight work and clears that room's private cache;
anonymous and static pages issue no workflow API calls. An unconfirmed admission
keeps its exact payload and idempotency key for an explicit retry.

Only a completed, accepted run with a saved artifact receipt offers a download.
The client verifies the exact streamed byte count and SHA-256 before handing the
JSON Blob to the browser. This handoff is not proof that the user saved the file.

Workflow tests live in `tests/unit/core/workflows`,
`tests/unit/components/workspace/workflow-room.dom.test.tsx` and
`tests/e2e/workflow-room.spec.ts`. The browser suite blocks service workers and
intercepts every API request, including a fail-closed fallback, so its synthetic
fixtures cannot trigger a paid provider call. Responsive checks cover 390, 768
and 1440px, 44px controls, focus and reduced motion. Fixture QA does not establish
physical iPhone installation or live provider acceptance.

## License

MIT License. See [LICENSE](../LICENSE) for details.
