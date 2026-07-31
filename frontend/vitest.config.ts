import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

// Vitest 配置：复用 vite react 插件 + @ 别名，jsdom 环境。
// 与 vite.config.ts 分离以避免 build 时误加载 test 配置。
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
  },
});
