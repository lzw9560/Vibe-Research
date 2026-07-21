# 构建阶段: Node 编译前端
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --legacy-peer-deps 2>&1 || npm install --legacy-peer-deps 2>&1
COPY . .
RUN ./node_modules/.bin/tsc -b && ./node_modules/.bin/vite build

# 运行阶段: nginx 托管静态文件 + 反代后端 API
FROM nginx:alpine
# 删除默认配置
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
