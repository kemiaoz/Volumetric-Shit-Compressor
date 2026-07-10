# Volumetric Shit Compressor

把一个结构清晰、有条理的 web 项目（HTML + 外链 CSS/JS，包括 ES Module）打包成一个
**功能完全不变、但代码交互错杂、无注释、无法一眼看懂结构**的巨型单文件 HTML。

拿去发给朋友，让他右键"查看网页源代码"的时候当场血压升高。

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

打开这个 html，**功能和原来一模一样**——按钮能点、计数器能加、样式没丢一个像素。
但源代码已经完全没法看：没注释、被压缩、CSS 和 JS 被拆成好几块散落在 body 各个角落，
JS 之间也互相看不出哪段是哪个原始文件的。

## 它是怎么做到"不破坏功能"的（重点）

单纯把代码打乱很容易，难的是打乱了还能正常跑。这个工具做了几件保证正确性的事：

- **JS 压缩用 [terser](https://github.com/terser/terser)**，不用老旧的 `jsmin`——后者不认识 ES6
  模板字符串（反引号），会把字符串内部的空格也删掉，悄悄改变页面实际显示的文字。
- **本地代码里所有的字符串/模板字符串边界都会被正确识别**，切分代码块时只在字符串外部、
  安全的语句边界（分号/闭合大括号）处下刀，不会把代码切断在字符串或函数中间。
- **CSS 块可以随意打散插入 `<body>` 各处**——因为浏览器只关心多个 `<style>` 标签之间的
  相对先后顺序（决定层叠优先级），不关心它们具体挂在 DOM 树的哪个位置。
- **JS 块统一放在 `</body>` 之前**（这本身也是网页开发的常见最佳实践），保证所有脚本执行时
  全部 DOM 元素都已经解析完毕，不会出现"脚本被插到某个元素前面、执行时那个元素还没出现"
  导致直接报错、页面打不开的情况。
- 插入点选在**闭合标签之后**（成为兄弟节点），而不是塞进 `<p>`、`<button>` 这类还有文字
  内容的元素内部，避免污染业务代码里可能会读取的 `.textContent` / `.innerHTML`。
- 如果入口脚本是 `<script type="module" src="main.js">`，且 `main.js` 内部用
  `import ... from './xxx.js'` 引用了其他本地模块（不管嵌套多少层），会调用
  [esbuild](https://esbuild.github.io/) 把整棵依赖树正确打包成一份语义等价的单文件代码
  （依赖关系、共享变量、求值顺序全部由 esbuild 保证正确），而不是自己写一个脆弱的
  正则去解析 import 语句。

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
  ES Module 也不会被正确打包），仍然可用但效果打折扣。

## License

MIT，随便玩，但别真的拿去搞破坏。
