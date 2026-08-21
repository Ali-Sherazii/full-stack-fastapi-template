import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react-swc"
import JavaScriptObfuscator from "javascript-obfuscator"
import { defineConfig, type Plugin } from "vite"

// Obfuscates each production chunk after minification. Runs only for
// `vite build`, never `vite dev`/`vite preview`, and must transform code
// as plain strings post-bundle (not per Rollup module) so cross-chunk
// import/export bindings stay intact.
function obfuscator(): Plugin {
  return {
    name: "obfuscator",
    apply: "build",
    enforce: "post",
    renderChunk(code) {
      const result = JavaScriptObfuscator.obfuscate(code, {
        compact: true,
        controlFlowFlattening: true,
        controlFlowFlatteningThreshold: 0.4,
        deadCodeInjection: true,
        deadCodeInjectionThreshold: 0.2,
        identifierNamesGenerator: "hexadecimal",
        ignoreImports: true,
        numbersToExpressions: true,
        renameGlobals: false,
        selfDefending: false,
        simplify: true,
        splitStrings: true,
        splitStringsChunkLength: 10,
        stringArray: true,
        stringArrayEncoding: ["base64"],
        stringArrayShuffle: true,
        stringArrayWrappersCount: 2,
        stringArrayWrappersChainedCalls: true,
        stringArrayWrappersParametersMaxCount: 4,
        stringArrayWrappersType: "function",
        stringArrayThreshold: 0.75,
        transformObjectKeys: true,
        unicodeEscapeSequence: false,
      })
      return { code: result.getObfuscatedCode(), map: null }
    },
  }
}

// https://vitejs.dev/config/
export default defineConfig({
  build: {
    outDir: "../backend/app/frontend",
    emptyOutDir: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  plugins: [
    tanstackRouter({
      target: "react",
      autoCodeSplitting: true,
    }),
    react(),
    tailwindcss(),
    obfuscator(),
  ],
})
