# 第三方檔案

這個資料夾放直接隨專案發佈的第三方程式，不經過 npm 或打包工具。

| 檔案 | 版本 | 授權 |
|---|---|---|
| `vue.esm-browser.prod.js` | Vue 3.5.45（含 template 編譯器的瀏覽器 ESM 版） | MIT，見 `vue.LICENSE` |

更新 Vue：從 npm 的 `vue` 套件取出 `dist/vue.esm-browser.prod.js` 覆蓋同名檔案，並更新上表的版本。

```bash
npm pack vue && tar xzf vue-*.tgz package/dist/vue.esm-browser.prod.js
```

字型 `../fonts/bricolage-grotesque.woff2` 是 Bricolage Grotesque 的拉丁字母可變字型（SIL OFL 1.1，見同資料夾的 LICENSE）。
