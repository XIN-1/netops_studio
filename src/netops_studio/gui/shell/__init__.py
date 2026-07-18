"""GUI 应用外壳（gui/shell）。

承载「应用骨架」而非具体业务：主窗口（MainWindow）、左侧导航面板（NavPanel），
以及它们所依赖的布局约定。具体功能页由 gui.* 各模块实现，经 app.tab_registry
以懒加载方式注入到 MainWindow 的堆叠工作区中。

层级关系：gui.shell 依赖 app（theme / tab_registry / i18n）与 gui.widgets
（如 ScrollBox），但不反向依赖任何业务模块，保持外壳的可复用性。
"""
