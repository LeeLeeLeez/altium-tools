// 桌面版入口：winsows 下 release 模式不弹控制台
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    altium_tools_lib::run()
}
