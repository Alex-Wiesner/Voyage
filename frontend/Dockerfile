# Use the official Bun image as the build platform (supports linux/amd64 and linux/arm64 natively)
FROM oven/bun:1.2.22-alpine AS builder

# Metadata labels for the Voyage image
LABEL maintainer="Voyage contributors" \
      version="v0.12.0" \
      description="Voyage — the ultimate self-hosted travel companion." \
      org.opencontainers.image.title="Voyage" \
      org.opencontainers.image.description="Voyage is a self-hosted travel companion that helps you plan, track, and share your adventures." \
      org.opencontainers.image.version="v0.12.0" \
      org.opencontainers.image.authors="Voyage contributors" \
      org.opencontainers.image.url="https://voyage.app" \
      org.opencontainers.image.source="https://github.com/Alex-Wiesner/voyage" \
      org.opencontainers.image.vendor="Voyage contributors" \
      org.opencontainers.image.created="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
      org.opencontainers.image.licenses="GPL-3.0"

# The WORKDIR instruction sets the working directory for everything that will happen next
WORKDIR /app

# Upgrade zlib to include Alpine security fixes
RUN apk upgrade --no-cache zlib

# Copy package files first for better Docker layer caching
COPY package.json bun.lock* ./

# Clean install all node modules using bun with frozen lockfile
RUN bun install --frozen-lockfile

# Copy the rest of the application files
COPY . .

# Remove the development .env file if present
RUN rm -f .env

# Build SvelteKit app
RUN bun run build

# Make startup script executable
RUN chmod +x ./startup.sh

# Keep only production dependencies for runtime image
RUN bun install --frozen-lockfile --production

# Runtime image contains only built app + runtime deps
FROM node:22-alpine AS runtime

WORKDIR /app

# Upgrade zlib and remove npm toolchain from runtime image
RUN apk upgrade --no-cache zlib \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack

# Copy build artifacts and production runtime dependencies
COPY --from=builder /app/build ./build
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/startup.sh ./startup.sh

# Ensure startup script is executable
RUN chmod +x ./startup.sh

# Change to non-root user for security
USER node:node

# Expose the port that the app is listening on
EXPOSE 3000

# Run startup.sh instead of the default command
CMD ["./startup.sh"]
