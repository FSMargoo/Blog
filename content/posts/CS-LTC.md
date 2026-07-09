---
title: 用 C# 进行 GPU 编程并复现 LTC
date: '2026-07-03'
category: Graphics
authors:
- name: Margoo
  email: qiuzhengyu@siggraph.org
abstract: 本文在 LTC 论文实现的背景下介绍了笔者最新开发的项目—Feather（EasyGPU 的前端）。Feather 是一个可用于 .NET10
  开发的 GPU 计算库，旨在简化 C# 中的 GPU 图形计算开发。其提供了自动可微、计算着色器、图形管线等一系列 API，让开发者可以只使用 C# 就可以编写
  GPU 上运行的加速代码，并在多个主流桌面平台运行。
keywords:
- GPU
- Feather
- LTC
- Graphics
tags:
- GPU
- Graphics
- Feather
slug: CS-LTC
---

本文主要展示使用我最新发布的实验性项目——[Feather](https://github.com/FeatherCompute/Feather) 编写的 LTC 拟合与渲染器。其使用了 Feather 提供的图形管线、自动可微与窗口 API 实现了完整的 LTC 拟合器与实时渲染器。

LTC 渲染器与拟合器的 GitHub 项目链接：[https://github.com/FeatherCompute/LTC](https://github.com/FeatherCompute/LTC)。

![fig:LTC-Result|本文中实现的 LTC 渲染器在 Sponza 中带有纹理的光源光照效果|width=80%](assets/images/LTC-Feather/preview.png)