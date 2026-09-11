# zpf-web-5t

**The signed-in studio lives under `/studio`** (2026-09-11): the shell, the
Studio composer, the Director canvas (`/studio/flows`, see FLOWS.md) and
Elements (`/studio/elements`). It talks to the FastAPI backend through the
same-origin proxy in `next.config.ts` (`API_UPSTREAM`), so run the Python app
first. The marketing page at `/` is the v0-generated landing.

This is a [Next.js](https://nextjs.org) project bootstrapped with [v0](https://v0.app).

## Built with v0

This repository is linked to a [v0](https://v0.app) project. You can continue developing by visiting the link below -- start new chats to make changes, and v0 will push commits directly to this repo. Every merge to `main` will automatically deploy.

[Continue working on v0 →](https://v0.app/chat/projects/prj_ul5LxD37s7KQ5P4iH1a4bbXtQdKm)

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

## Learn More

To learn more, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.
- [v0 Documentation](https://v0.app/docs) - learn about v0 and how to use it.
