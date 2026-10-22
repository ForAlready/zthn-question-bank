import { defineConfig } from 'vitest/config'
import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'

// 从 Nuxt 的依赖上下文解析 Vue 插件，兼容 pnpm 下插件未直接安装到项目前端根目录的布局。
const requireFromNuxt = createRequire(createRequire(import.meta.url).resolve('nuxt/package.json'))
export default defineConfig(async () => {
    const { default: vue } = await import(pathToFileURL(requireFromNuxt.resolve('@vitejs/plugin-vue')).href)
    return {
        plugins: [vue()],
        test: {
            environment: 'happy-dom',
            include: ['app/**/*.{test,spec}.ts'],
        },
        resolve: {
            alias: {
                '@': fileURLToPath(new URL('./app', import.meta.url)),
                '~': fileURLToPath(new URL('./app', import.meta.url)),
            },
        },
    }
})
