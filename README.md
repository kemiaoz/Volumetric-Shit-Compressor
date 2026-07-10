# Volumetric Shit Compressor

把一个结构清晰、有条理的 web 项目（HTML + 外链 CSS/JS，包括 ES Module）打包成一个
**功能不变、代码交互错杂、无注释、无法一眼看懂结构**的巨型单文件 HTML。

## 效果

**打包前**（清晰的项目结构）

```
myproject/
├── index.html
├── css/
│   └── style.css
└── js/
    ├── main.js      (type="module", 入口)
    ├── ui.js
    └── state.js
```

**打包后**（`vsc_output.html`，单文件）

```html
<!DOCTYPE html><html><head>...</head><body><h1>Click Counter</h1><button id="btn">Click me</button><style>button{padding:10px 20px;font-size:16px;cursor:pointer}</style><style>h1{color:#333}</style>...<script>(()=>{var count=0;!function(){const btn=document.getElementById("btn")...
```

反正就是变成屎。Volumetric Shit Compression。

## 实现

- JS 压缩使用 [terser](https://github.com/terser/terser)
- 切分代码块在字符串外部、语句边界（分号/闭合大括号）处
- CSS 块随意打散插入 `<body>` 各处，JS 块统一放在 `</body>` 之前
- 插入点选在闭合标签之后成为兄弟节点
- 互相引用的js脚本先调用[esbuild](https://esbuild.github.io/) 打包成单文件

## 安装

```bash
git clone https://github.com/<你的用户名>/volumetric-shit-compressor.git
cd volumetric-shit-compressor

# Python 依赖 (CSS 压缩)
pip install csscompressor --break-system-packages

# Node 依赖 (可选但强烈推荐; 没装也能跑, 只是 JS 不会被压缩/去注释,
# 更不能正确处理 ES Module 的 import)
npm install
```

## 用法

```bash
python3 volumetric_shit_compressor.py <项目根目录> <入口html文件名> -o output.html [--chunks 6] [--seed 42]
```

用仓库自带的示例项目试一下：

```bash
python3 volumetric_shit_compressor.py examples/demo-project index.html -o output.html --chunks 8
open output.html   # macOS; Linux 用 xdg-open, Windows 直接双击
```

| 参数 | 说明 |
|---|---|
| `project_dir` | 项目根目录 |
| `entry_html` | 入口 html 文件名（相对 `project_dir`） |
| `-o, --output` | 输出文件路径，默认 `vsc_output.html` |
| `--chunks` | CSS / JS 各自打散成几块，默认 6，数字越大越碎越乱 |
| `--seed` | 随机种子；固定后每次生成结果一致，方便你自己先检查效果 |

## 支持的项目结构

- `<link rel="stylesheet" href="...">` 外链 CSS
- `<script src="...">` 普通外链 JS
- `<script type="module" src="...">` ES Module 入口，及其递归 `import` 的所有**本地**文件
- html 中原有的内联 `<style>` / `<script>`

## 已知限制

- 只处理本地相对路径的资源，不会打包 CDN 上的第三方库（`<script src="https://...">`
  这种会被当作外部资源保留原样，不受影响，也不会被内联）。
- `import` 的必须是本地文件；`import` npm 包（如 `import _ from 'lodash'`）需要项目本身
  能被 esbuild 正常解析（比如 node_modules 存在），否则 esbuild 打包会失败，脚本会打印
  警告并退回读取原文——这种情况下最终 html 里的 import 语句大概率无法工作，需要你自己检查。
- 如果项目里有**多个** `<script type="module">` 入口，且它们之间 import 了同一个共享模块
  （比如一个共享状态的 `store.js`），浏览器原生 ES Module 是"只加载求值一次、多处共享同一份
  实例"，但这里是按入口分别打包的，每个入口会各自内嵌一份该模块的独立副本——如果那个共享
  模块里有需要跨入口共享的状态，打包后行为可能和原项目不一致。绝大多数项目只有一个入口，
  不会碰到这个问题；工具检测到这种情况会打印提示。
- 没装 `terser` / `esbuild` 时会自动退回一个更保守的兜底方案（只去注释、不压缩空白，
  ES Module 也不会被正确打包），仍然可用，但效果较差。

## Acknowledgements

做小游戏学 web 学疯了的产物。此项目仅供娱乐，写代码、测试、修 bug 包括大部分 readme 都由 Claude 完成……

## License

MIT。应该没什么社会危害性。
