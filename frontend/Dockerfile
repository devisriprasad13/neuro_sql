# ================================================================== #
# NeuroSQL Frontend — Dockerfile
#
# Multi-stage build:
#   Stage 1 (development): Vite dev server with hot reload
#   Stage 2 (production):  Static files served by Nginx
#
# Docker Compose uses the 'development' stage.
# Cloud deployment uses the 'production' stage.
# ================================================================== #


# ================================================================== #
# Stage 1 — Development
#
# Runs the Vite development server with hot module replacement.
# Source code is mounted as a volume so changes reflect instantly
# without rebuilding the container.
# ================================================================== #
FROM node:20-alpine AS development

# Set working directory
WORKDIR /app

# Install dependencies first — before copying source code.
#
# Same caching strategy as the backend Dockerfile:
# package.json and package-lock.json rarely change.
# Copying them first means Docker caches the npm install layer.
# Code changes don't trigger a full reinstall.
COPY package.json package-lock.json* ./

# Install all dependencies including devDependencies
# (we need Vite, TypeScript compiler, etc. in development)
#
# --legacy-peer-deps: avoids peer dependency conflicts
# that are common in React ecosystems
RUN npm install --legacy-peer-deps

# Copy the rest of the source code
# In development this is overridden by the volume mount in docker-compose
# but we copy here so the image works standalone too
COPY . .

# Document the port Vite listens on
EXPOSE 5173

# Start Vite development server
#   --host 0.0.0.0  — listen on all interfaces (required inside Docker)
#                     without this, the server is only accessible
#                     from inside the container, not from your browser
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]


# ================================================================== #
# Stage 2 — Builder (for production)
#
# Compiles React + TypeScript into optimized static files.
# Output: /app/dist folder containing HTML, CSS, and JS bundles.
# This stage is not used in development.
# ================================================================== #
FROM node:20-alpine AS builder

WORKDIR /app

# Copy and install dependencies
COPY package.json package-lock.json* ./
RUN npm install --legacy-peer-deps

# Copy source code
COPY . .

# Build arguments that become environment variables during build
# These are baked into the static JS bundle at compile time
ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_APP_ENV=production
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_APP_ENV=$VITE_APP_ENV

# Compile TypeScript and bundle with Vite
# Output goes to /app/dist
RUN npm run build


# ================================================================== #
# Stage 3 — Production
#
# Minimal Nginx image serving the compiled static files.
# No Node.js. No npm. Just Nginx and static files.
# Image size: ~25MB vs ~400MB for a Node.js image.
# ================================================================== #
FROM nginx:alpine AS production

# Remove default Nginx welcome page
RUN rm -rf /usr/share/nginx/html/*

# Copy compiled static files from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy custom Nginx configuration
# We will create this file in Milestone 15
# COPY nginx.conf /etc/nginx/conf.d/default.conf

# Nginx listens on port 80 by default
EXPOSE 80

# Start Nginx in foreground mode
# (Docker requires the main process to run in foreground)
CMD ["nginx", "-g", "daemon off;"]