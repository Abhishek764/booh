import { defineConfig, globalIgnores } from "eslint/config";
import tsParser from "@typescript-eslint/parser";

export default defineConfig([
  {
    files: ["**/*.{js,mjs,ts,tsx}"],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaFeatures: { jsx: true },
        sourceType: "module",
      },
      globals: {
        URL: "readonly",
        window: "readonly",
        document: "readonly",
        HTMLButtonElement: "readonly",
      },
    },
    rules: {
      "no-undef": "error",
      "no-unused-vars": "off",
    },
  },
  globalIgnores([".next/**", "node_modules/**", "next-env.d.ts", "test-results/**", "playwright-report/**"]),
]);
