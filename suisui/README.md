# 岁岁 (Suisui) — 桌面宠物猫咪 🐱

可爱的深蓝色小猫，住在你的桌面上！

## 启动方法

```bash
bash /Users/sue/sue-tech/suisui/start.sh
```

或直接运行：

```bash
~/sue-tech/.venv/bin/python /Users/sue/sue-tech/suisui/main.py
```

## 功能说明

| 操作 | 效果 |
|------|------|
| 左键点头 | 岁岁闭眼摇头，显示"嗯嗯～" |
| 左键点肚子 | 发出喵声，显示"喵！" |
| 右键 | 弹出菜单（睡觉/提醒设置/退出） |
| 拖动猫咪 | 移动到屏幕任意位置 |

## 自动提醒

每 **45 分钟**岁岁会跑到屏幕中央，提醒你：
- 起来动一动
- 喝水
- 站一会儿
- 眨眨眼

## 停止运行

```bash
pkill -f "python.*suisui/main.py"
```

## 文件结构

```
suisui/
  main.py     # 主程序
  start.sh    # 启动脚本
  README.md   # 本文件
  suisui.log  # 运行日志（启动后生成）
```
