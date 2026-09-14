# The Next.js studio (web/) as its own Fly app -- backlog #14's split, the
# front-end half. Standalone output (next.config.ts) so the runtime image
# carries only what the server needs. The API is the FastAPI app on its own
# Fly app; this image reaches it THROUGH ITS OWN ORIGIN (the Next rewrites,
# API_UPSTREAM at runtime) so the session cookie is first-party -- a
# cross-site cookie is one Safari and Chrome refuse to send (2026-09-14).
# NEXT_PUBLIC_API_URL therefore stays EMPTY; NEXT_PUBLIC_AUTH_ORIGIN is the
# API's public origin, where sign-in and sign-out navigate (OAuth runs
# there and hands the session back via /auth/handoff). Both are baked in at
# build time because they are public, client-side values; the backend
# names this origin in FRONTEND_ORIGINS.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=
ARG NEXT_PUBLIC_AUTH_ORIGIN
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_AUTH_ORIGIN=$NEXT_PUBLIC_AUTH_ORIGIN \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
