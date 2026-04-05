FROM node:22-slim
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .

# Build args become NEXT_PUBLIC env vars at build time
ARG NEXT_PUBLIC_AUTH_MODE=firebase
ARG BACKEND_URL=http://localhost:8100
ENV NEXT_PUBLIC_AUTH_MODE=$NEXT_PUBLIC_AUTH_MODE
ENV BACKEND_URL=$BACKEND_URL

RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
