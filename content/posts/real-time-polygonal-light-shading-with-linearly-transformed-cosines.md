---
title: 《Real-Time Polygonal-Light Shading with Linearly Transformed Cosines》论文阅读与思考
date: '2026-06-14'
category: Rendering
authors:
- name: Margoo
  email: qiuzhengyu@siggraph.org
abstract: 《Real-time polygonal-light shading with linearly transformed cosines》是由
  Eric Heitz 等人于 2016 年在 TOG 上发表的一篇工作。其利用一个 3x3 的矩阵将一个截断余弦分布变换为复杂的 BRDF 分布模型，并利用其闭式积分表达式计算光照结果，实现了对直接光照的实时高效求解。本文是笔者对该论文的阅读笔记以及一些思考。其中会对该论文的各个细节进行推导和解释。本文会尽量从零开始讲起，降低读者的理解难度，其中会补充许多论文所需的前置知识，基础较弱的读者也可以尝试阅读。
keywords:
- LTC
- Realtime Rendering
- Rendering
tags:
- Realtime Rendering
- Rendering
- Computer Graphics
- Note
slug:      real-time-polygonal-light-shading-with-linearly-transformed-cosines
bibliography:
  heitz2016: "Eric Heitz, Jonathan Dupuy, Stephen Hill, and David Neubelt. 2016. Real-time polygonal-light shading with linearly transformed cosines. ACM Trans. Graph. 35, 4, Article 41 (July 2016), 8 pages. https://doi.org/10.1145/2897824.2925895"
  baum1989: "D. R. Baum, H. E. Rushmeier, and J. M. Winget. 1989. Improving radiosity solutions through the use of analytically determined form-factors. SIGGRAPH Comput. Graph. 23, 3 (July 1989), 325–334. https://doi.org/10.1145/74334.74367."
  james1986: "James T. Kajiya. 1986. The rendering equation. SIGGRAPH Comput. Graph. 20, 4 (Aug. 1986), 143–150. https://doi.org/10.1145/15886.15902"
---

## 引入
Eric Heitz 等人在 2016 年 TOG 上发布的工作《Real-Time Polygonal-Light Shading with Linearly Transformed Cosines》[@heitz2016]（下文简称 LTC）通过将一个 $3\times 3$ 的矩阵应用到一个截断余弦分布 $D_o\left(\boldsymbol{\omega}_o\right)$ 的方向向量 $\boldsymbol{\omega}_o$ 上，得到了一个近似特定视角和粗糙度下目标 BRDF 形状的分布 $D\left(\boldsymbol{\omega}\right)$。随后，LTC 利用原始截断余弦分布在多边形域上的闭式积分表达式，计算着色点接收到的直接光照贡献。由于原始分布的闭式表达式可以解析计算[@baum1989]，因此可以达到实时求解的性能要求。该方法易于实现，且可以使用低存储成本的预计算形式进一步降低实时计算成本，因此被广泛应用于游戏引擎等侧重实时视觉效果的场景。

本文将以笔者自身的理解分析本篇论文。本文会尽量从零开始讲起，降低读者的理解难度，其中会补充许多论文所需的前置知识，基础较弱的读者也可以尝试阅读。


## 前置知识
### $S^2$ 球面上的分布
LTC 整篇文章都围绕一个主题展开：$S^2=\left\{\boldsymbol{\omega}\in\mathbb{R}^3|\left\lVert \boldsymbol{\omega} \right\rVert=1\right\}$ 球面上的密度函数或权重分布。只有理解这个概念才能理解整个 LTC。我们研究的对象是定义域在球面上的分布函数 $D\left(\boldsymbol{\omega}\right)$。考虑渲染方程[@james1986]：

\begin{equation}
  L_o(\mathbf{x}, \boldsymbol{\omega}_o) = L_e(\mathbf{x}, \boldsymbol{\omega}_o) + \int_{\Omega} f_r(\mathbf{x}, \boldsymbol{\omega}_i, \boldsymbol{\omega}_o) \, L_i(\mathbf{x}, \boldsymbol{\omega}_i) \, (\boldsymbol{\omega}_i \cdot \mathbf{n}) \, \text{d}\boldsymbol{\omega}_i
\end{equation}

在 LTC 中，我们关心如何在不考虑遮挡、且只有多边形光源的情况下解析地求解积分 $\int_{\Omega} f_r(\mathbf{x}, \boldsymbol{\omega}_i, \boldsymbol{\omega}_o) \, L_i(\mathbf{x}, \boldsymbol{\omega}_i) \, (\boldsymbol{\omega}_i \cdot \mathbf{n}) \, \text{d}\boldsymbol{\omega}_i$，我们将其分成两部分，一部分是 $L_i(\mathbf{x}, \boldsymbol{\omega}_i)$，另一部分是 $f_r(\mathbf{x}, \boldsymbol{\omega}_i, \boldsymbol{\omega}_o) (\boldsymbol{\omega}_i \cdot \mathbf{n})$。令 $D(\boldsymbol{\omega}_i)=f_r\left(\mathbf{x}, \boldsymbol{\omega}_i, \boldsymbol{\omega}_o\right)\left(\boldsymbol{\omega}_i\cdot\mathbf{n}\right)$，这正是 LTC 所关注的在球面上的分布。所谓球面分布，可以想象为一个定义在球面上的函数。例如 $D\left(\boldsymbol{\omega}\right)=\max\left\{0, \boldsymbol{\omega}\cdot\mathbf{n}\right\}$ 的图像如[@fig:cosine_distribution] 所示。其中 $\boldsymbol{\omega}$ 是从球心到球面的单位向量，而 $\mathbf{n}$ 是法向量。

![fig:cosine_distribution|在 $S^2$ 上 $D\left(\boldsymbol{\omega}\right)=\max\left\{0, \boldsymbol{\omega}\cdot\mathbf{n}\right\}$ 的图像|width=45%](assets/images/LTC/clamp_cosine_distribution.png)

这个分布 $D\left(\boldsymbol{\omega}\right)$ 可以视作对不同方向的 $L_i\left(\mathbf{x},\boldsymbol{\omega}_i\right)$ 的权重，可以将其当作一个积分核或权重函数。这里的“分布”不一定已经归一化为概率密度；当它的积分被归一化为 $1$ 时，才可以进一步把它解释为概率分布。

## 论文基本思路概述

在一般的渲染任务中，$D\left(\boldsymbol{\omega}\right)$ 是非常复杂的，使得积分 $\int_{\Omega} f_r(\mathbf{x}, \boldsymbol{\omega}_i, \boldsymbol{\omega}_o) \, L_i(\mathbf{x}, \boldsymbol{\omega}_i) \, (\boldsymbol{\omega}_i \cdot \mathbf{n}) \, \text{d}\boldsymbol{\omega}_i$ 几乎不可能被解析计算。因此 LTC 给出的解决方案是把一个简单的原始分布 $D_o\left(\boldsymbol{\omega}_o\right)$ 通过一个矩阵 $M$ 变换成一个新的分布 $D\left(\boldsymbol{\omega}\right)$，从而使得这个新的分布 $D\left(\boldsymbol{\omega}\right)$ 能够逼近真正的目标分布 $f_r(\mathbf{x}, \boldsymbol{\omega}_i, \boldsymbol{\omega}_o) \, (\boldsymbol{\omega}_i \cdot \mathbf{n})$。

注意矩阵 $M$ 的作用对象不是分布本身，而是其方向向量：

\begin{equation}
  \boldsymbol{\omega}=\frac{M\boldsymbol{\omega}_o}{\left\lVert M\boldsymbol{\omega}_o \right\rVert}\\
  \boldsymbol{\omega}_o\xrightarrow{M}\boldsymbol{\omega}
\end{equation}

![fig:clamp_cosine_and_GGX|截断余弦变换为 GGX 模型的 BRDF，左为余弦变换，右为 GGX 模型的 BRDF|width=60%](assets/images/LTC/clamp_cosine_and_GGX.png)

反过来，如果我们找到了一个可逆的矩阵可以把 $\boldsymbol{\omega}_o$ 变换为 $\boldsymbol{\omega}$，那么我们可以用它的逆矩阵把 $\boldsymbol{\omega}$ 变换为 $\boldsymbol{\omega}_o$：

\begin{equation}
  \boldsymbol{\omega}_o=\frac{M^{-1}\boldsymbol{\omega}}{\left\lVert M^{-1}\boldsymbol{\omega} \right\rVert}\\
  \boldsymbol{\omega}\xrightarrow{M^{-1}}\boldsymbol{\omega}_o
\end{equation}

而这就是 LTC 解决多边形光源光照的关键所在。试想一个多边形光源，其顶点集合为 $\text{P}$，构成了一个面 $\Omega_{P}$。在前文背景下，我们可以通过 $M^{-1}$ 将 $\text{P}$ 中的所有顶点变换为新的顶点 $\text{P}^\prime$，并得到一个新的面 $\Omega_{P}^\prime$。再利用截断余弦空间中截断余弦分布本身简单优良的性质进行光照的解析计算。

这里值得注意的是：在原本的渲染模型下，其实已经默认了顶点都处于 $D\left(\boldsymbol{\omega}\right)$ 分布下了。所以 LTC 在实际渲染中扮演的不是一个正向变换的角色，而是一个反向变换的角色：通过将当前空间中的顶点利用逆矩阵 $M^{-1}$ 变换到更简单的分布空间（如原文中使用的是截断余弦变换）中，再在更简单的分布空间中进行解析的光照计算。

![fig:polygon_transform|多边形变换示意图，通过将原有的多边形顶点通过 $M^{-1}$ 变换到截断余弦变换空间，再利用截断余弦变换本身的封闭解析式进行光照计算|width=70%](assets/images/LTC/polygon_transform.png)

这就是 LTC 的基本思路。

## 线性变换球面分布

接下来我们将正式开始讨论 LTC 的技术细节。原文中提出了一个叫线性变换球面分布（Linearly Transformed Spherical Distribution，LTSD）的概念。其指的就是由原始分布 $D_o\left(\boldsymbol{\omega}_o\right)$ 经过矩阵 $M$ 变换得到的一系列子分布 $D_o\left(\boldsymbol{\omega}_o\right)\xrightarrow{M_{k}}D_k\left(\boldsymbol{\omega}\right)$。其中 $D_o$ 代表原始分布，$D_k$ 代表通过矩阵 $M_k$ 变换 $\boldsymbol{\omega}_o$ 得到的子分布。

接下来我们开始进行具体推导。由前文所述我们可以知道，我们通过一个 $M$ 将原本的 $\boldsymbol{\omega}_o$ 变换为 $\boldsymbol{\omega}$，也就是说 $\boldsymbol{\omega}=\dfrac{M\boldsymbol{\omega}_o}{\left\lVert M\boldsymbol{\omega}_o \right\rVert}$。注意这里因为要确保 $\boldsymbol{\omega}$ 是单位向量，因此需要对其进行归一化。

由于变换过程中，我们需要遵循守恒关系，因此：

\begin{equation}
  D\left(\boldsymbol{\omega}\right)\text{d}\boldsymbol{\omega}=D_o\left(\boldsymbol{\omega}_o\right)\text{d}\boldsymbol{\omega}_o
\end{equation}

注意这里可能比较难理解，事实上，由前文所述可知，$D(\boldsymbol{\omega})$ 等都是密度函数。我们可以把其想象成 $\rho$。变换 $M$ 本质上是对其进行形变，其总“质量”依然保持不变。上式可以理解为 $\rho V=\rho_o V_o$，其中 $V$、$V_o$ 代表的是两个密度函数空间下的单位体积。也就是“质量守恒”，如[@fig:mass_conservation]所示。

![fig:mass_conservation|质量守恒示意图|width=60%](assets/images/LTC/mass_conservation.png)

得到：

\begin{equation}
  D\left(\boldsymbol{\omega}\right)=D_o\left(\boldsymbol{\omega}_o\right)\dfrac{\text{d}\boldsymbol{\omega}_o}{\text{d}\boldsymbol{\omega}}
\end{equation}

现在的目标即为求出 $\dfrac{\text{d}\boldsymbol{\omega}_o}{\text{d}\boldsymbol{\omega}}$ 的表达式。这里提供两种方法，第一种方法是论文原文附录提供的证明。第二种方法是我给出的方法。个人认为我的方法会比原论文方法更为简洁方便。

### 雅可比因子推导

观察 $\dfrac{\text{d}\boldsymbol{\omega}_o}{\text{d}\boldsymbol{\omega}}$，其为该变换过程的雅可比因子。

考虑立体角的定义：

\begin{equation}
  \label{eq:solid_angle}
  \text{d}\Omega=\frac{\text{d}A}{r^2}
\end{equation}

其中 $r$ 是距离球心的距离，$\text{d}A$ 是面积微元。而当位于单位球体上时 $r=1$，也就退化为 $\text{d}\Omega=\text{d}A$。于是此时 $\text{d}\Omega=\text{d}\boldsymbol{\omega}$。[@eq:solid_angle] 是接下来两种推导方法的基石。

#### 论文方法

论文首先选取了一个任意方向向量 $\boldsymbol{\omega}_o$，并且在球面上的切平面内选取了两个相互垂直的向量 $\boldsymbol{\omega}_1$ 和 $\boldsymbol{\omega}_2$，组成了一个正交基 $\left\{\boldsymbol{\omega}_1, \boldsymbol{\omega}_2, \boldsymbol{\omega}_o\right\}$ 如[@fig:spherical_axis]。此时其对应的立体角为：

\begin{equation}
  \text{d}\boldsymbol{\omega}_o=\text{d}A_o
\end{equation}

注意由于此处为单位球体，因此 $r=1$。

![fig:spherical_axis|在球面上的切平面中心为原点选取一组正交基 $\left\{\boldsymbol{\omega}_1, \boldsymbol{\omega}_2, \boldsymbol{\omega}_o\right\}$|width=30%](assets/images/LTC/spherical_axis.png)

而在经过变换后，这个正交基变成了 $\left\{M\boldsymbol{\omega}_1, M\boldsymbol{\omega}_2, \mathbf{n}\right\}$ 如[@fig:transformed_spherical_axis]，假设其法向量 $\mathbf{n}$ 与 $\boldsymbol{\omega}$ 的夹角为 $\theta$，那么变换后的立体角为：

\begin{equation}
  \text{d}\boldsymbol{\omega}=\frac{\text{d}A\cos\theta}{r^2}
\end{equation}

![fig:transformed_spherical_axis|变换后的切平面的正交基变为 $\left\{M\boldsymbol{\omega}_1, M\boldsymbol{\omega}_2, \mathbf{n}\right\}$，平面法向量 $\mathbf{n}$ 与 $\boldsymbol{\omega}$ 的夹角为 $\theta$|width=40%](assets/images/LTC/transformed_axis.png)

可以得到：

\begin{equation}
  \text{d}A_o=\left\lVert \boldsymbol{\omega}_1\times \boldsymbol{\omega}_2 \right\rVert \\
  \text{d}A=\left\lVert M\boldsymbol{\omega}_1\times M\boldsymbol{\omega}_2 \right\rVert \\
  r=\left\lVert M\boldsymbol{\omega}_o \right\rVert\\
  \cos\theta=\left\langle\frac{M\boldsymbol{\omega}_o}{\left\lVert M\boldsymbol{\omega}_o \right\rVert}, \frac{M\boldsymbol{\omega}_1\times M\boldsymbol{\omega}_2}{\left\lVert M\boldsymbol{\omega}_1\times M\boldsymbol{\omega}_2 \right\rVert}\right\rangle
\end{equation}

代入得到：

\begin{equation}
  \frac{\text{d}\boldsymbol{\omega}_o}{\text{d}\boldsymbol{\omega}}=\frac{\left|\det\left(M^{-1}\right)\right|}{\left\lVert M^{-1}\boldsymbol{\omega} \right\rVert^3}
\end{equation}

#### 体积法

事实上，论文方法理解难度较高，且计算量大。但胜在直接。事实上我们可以把面积问题转换为体积问题。考虑 $\text{d}\boldsymbol{\omega}_o$ 和 $\text{d}\boldsymbol{\omega}$ 在空间中对应的两个锥体体积如[@fig:cone]：

\begin{equation}
  \text{d}V_o=\dfrac{1}{3}\text{d}\boldsymbol{\omega}_o
\end{equation}
\begin{equation}
  \text{d}V=\dfrac{1}{3}\text{d}\boldsymbol{\omega}r^3
\end{equation}


![fig:cone|$\text{d}\boldsymbol{\omega}$ 和 $\text{d}\boldsymbol{\omega}_o$ 所对应的锥体|width=30%](assets/images/LTC/cone.png)

其中 $r=\left\lVert M\boldsymbol{\omega}_o\right\rVert$。由于 $\boldsymbol{\omega}=\dfrac{M\boldsymbol{\omega}_o}{\left\lVert M\boldsymbol{\omega}_o \right\rVert}$，因此也有 $r=\dfrac{1}{\left\lVert M^{-1}\boldsymbol{\omega}\right\rVert}$。又变换后的新体积有 $\text{d}V=\left|\det\left(M\right)\right|\text{d}V_o$，代入简单化简就可以得到：

\begin{equation}
  \frac{\text{d}\boldsymbol{\omega}_o}{\text{d}\boldsymbol{\omega}}=\frac{\left|\det\left(M^{-1}\right)\right|}{\left\lVert M^{-1}\boldsymbol{\omega} \right\rVert^3}
\end{equation}

于是

\begin{equation}
  D\left(\boldsymbol{\omega}\right)=D_o\left(\frac{M^{-1}\boldsymbol{\omega}}{\left\lVert M^{-1}\boldsymbol{\omega}\right\rVert}\right)\frac{\left|\det\left(M^{-1}\right)\right|}{\left\lVert M^{-1}\boldsymbol{\omega} \right\rVert^3}
\end{equation}

其中 $D_o$ 的输入仍然是单位方向，因此需要对 $M^{-1}\boldsymbol{\omega}$ 进行归一化。

笔者个人认为该方法更为简单巧妙，且计算量也会更小。而这也是我几天前发布的[线性代数题](https://www.margoo.icu/posts/546c8d07.html)的证明。

## LTSDs 的性质

对于 LTSDs，原文给出了其几个性质：

1. 形状不变性（Shape Invariance）：由于最后都会进行归一化操作，所以如果有一系列 LTCs，其原始分布相同，使用的变换矩阵 $M_\lambda=\lambda M$ 其中 $M$ 是任意可变矩阵，那么这一系列 LTCs 簇 $\left\{D_\lambda\left(\boldsymbol{\omega}\right)|D_o\left(\boldsymbol{\omega}_o\right)\xrightarrow{M_\lambda}D_\lambda\left(\boldsymbol{\omega}\right)\right\}$ 都是等效的。
2. 中位向量（Median Vector）不变：如果向量 $\mathbf{a}$ 在原本的分布中是中位向量，即任意包含该向量的平面都可以把该分布分为两个完全相等，那么在经过变换后得到的变量 $M\mathbf{a}$ 依然还是中位变量。

变换后得到的 LTC 与原分布在域上的积分相同：

\begin{equation}
  \int_{\Omega}D\left(\boldsymbol{\omega}\right)\text{d}\boldsymbol{\omega}=\int_{\Omega}D_o\left(\boldsymbol{\omega}_o\right)\frac{\text{d}\boldsymbol{\omega}_o}{\text{d}\boldsymbol{\omega}}\text{d}\boldsymbol{\omega}=\int_{\Omega_o}D_o\left(\boldsymbol{\omega}_o\right)\text{d}\boldsymbol{\omega}_o
\end{equation}

## 用线性余弦变换逼近 BRDFs

关于原分布 $D_o\left(\boldsymbol{\omega}_o\right)$ 的选取，原论文采用了截断余弦分布：

\begin{equation}
  D_o\left(\boldsymbol{\omega}_o\right)=\frac{1}{\pi}\max\left\{0, \boldsymbol{\omega}_o\cdot\mathbf{n}\right\}
\end{equation}

并选择逼近使用 GGX 模型的 BRDF：

\begin{equation}
  D\left(\boldsymbol{\omega}_l\right)\approx\rho\left(\boldsymbol{\omega}_v, \boldsymbol{\omega}_l\right)\cos\theta_l
\end{equation}

其中 $\rho\left(\boldsymbol{\omega}_v, \boldsymbol{\omega}_l\right)$ 表示 BRDF，$\cos\theta_l$ 来自渲染方程中的余弦项，$\boldsymbol{\omega}_v$ 表示观察方向，$\boldsymbol{\omega}_l$ 表示入射光方向。原论文中只讨论各向同性的材料，因此该 BRDF 只依赖于观察方向 $\boldsymbol{\omega}_v=\left(\sin\theta_v,0,\cos\theta_v\right)$ 和粗糙度 $\alpha$ 确定。考虑变换矩阵

\begin{equation}
  M=\begin{pmatrix}
  m_{11} & m_{12} & m_{13} \\
  m_{21} & m_{22} & m_{23} \\
  m_{31} & m_{32} & m_{33} \\
  \end{pmatrix}
\end{equation}

由于我们考虑各向同性材料，所以该材料的瓣（lobe）应该是关于 $xz$ 平面对称的，也即：

\begin{equation}
  D(\boldsymbol{\omega}=\left(x,y,z\right))=D(\boldsymbol{\omega}=\left(x,-y,z\right))
\end{equation}

为了让 LTC 的矩阵参数化显式满足这一对称性，可以选择令变换矩阵与关于 $xz$ 平面的反射矩阵 $R$ 对易：

\begin{equation}
  R=\begin{pmatrix}
    1 & 0 & 0 \\
    0 & -1 & 0 \\
    0 & 0 & 1
  \end{pmatrix} \\
  MR=RM
\end{equation}

写完整：

\begin{equation}
  \begin{pmatrix}
  m_{11} & -m_{12} & m_{13} \\
  m_{21} & -m_{22} & m_{23} \\
  m_{31} & -m_{32} & m_{33}
  \end{pmatrix}=\begin{pmatrix}
  m_{11} & m_{12} & m_{13} \\
  -m_{21} & -m_{22} & -m_{23} \\
  m_{31} & m_{32} & m_{33}
  \end{pmatrix}
\end{equation}

由这一参数化约束得到 $m_{12}=m_{21}=m_{23}=m_{32}=0$，于是：

\begin{equation}
  M=\begin{pmatrix}
  m_{11} & 0 & m_{13} \\
  0 & m_{22} & 0 \\
  m_{31} & 0 & m_{33}
  \end{pmatrix}
\end{equation}

注意，前文已经讨论过，LTSDs 具有形状不变性（Shape Invariance），一系列 LTCs 簇 $\left\{D_\lambda\left(\boldsymbol{\omega}\right)|D_o\left(\boldsymbol{\omega}_o\right)\xrightarrow{M_\lambda}D_\lambda\left(\boldsymbol{\omega}\right)\right\}$ 都是等效的。故可通过 $\dfrac{1}{m_{33}}M$ 消去 $m_{33}$ 的一个自由度，并重新命名得到：

\begin{equation}
M=\begin{pmatrix}
a & 0 & b \\
0 & c & 0 \\
d & 0 & 1
\end{pmatrix}
\end{equation}

这也正是原论文给出的矩阵形式。关于该矩阵的训练，原论文依据经验指出 $L^3$ 损失函数可以得到最佳的视觉效果。

![fig:ltsd_performance|原论文给出的在不同 $\theta_v$ 与 $\alpha$ 下 LTC 拟合结果图|width=70%](assets/images/LTC/performance_of_LTC.png)

#### 拟合矩阵存储方式

由前面的讨论以及原文指出，我们只需要存储一系列 $\theta_v$ 和 $\alpha$ 不同的 $M^{-1}_{\theta_v,\alpha}$，对于具体的数值再通过线性插值得到具体的 $M^{-1}$。

## 使用 LTC 进行实时多边形光照解算

试想一个多边形光源，其顶点集合为 $\text{P}$，构成了一个面 $\Omega_{P}$。其经过 $M^{-1}$ 变换后得到的顶点集合和面为 $\text{P}_o$、$\Omega_{Po}$。计算其光照的本质是计算积分：

\begin{equation}
  I=\int_{\Omega_P}L\left(\boldsymbol{\omega}_l\right)\rho\left(\boldsymbol{\omega}_v, \boldsymbol{\omega}_l\right)\cos\theta_l\,\text{d}\boldsymbol{\omega}_l
\end{equation}

其中 $L\left(\boldsymbol{\omega}_l\right)$ 是由多边形光源在 $\boldsymbol{\omega}_l$ 方向提供的入射辐射亮度。而在 LTC 下，$\rho\left(\boldsymbol{\omega}_v, \boldsymbol{\omega}_l\right)\cos\theta_l$ 被近似为 $D\left(\boldsymbol{\omega}_l\right)$：

\begin{equation}
  I=\int_{\Omega_{P}}L(\boldsymbol{\omega}_l)D\left(\boldsymbol{\omega}_l\right)\text{d}\boldsymbol{\omega}_l=\int_{\Omega_{Po}}L(\boldsymbol{\omega}_{lo})D_o\left(\boldsymbol{\omega}_{lo}\right)\text{d}\boldsymbol{\omega}_{lo}
\end{equation}

### 固定纯色多边形光照解算

对于固定纯色的多边形，其光照解算相对容易。此时 $\forall \boldsymbol{\omega}\in S^2$，$L\left(\boldsymbol{\omega}\right)=L$，其中 $L$ 为一定值，则：

\begin{equation}
  \int_{\Omega_{P}}L(\boldsymbol{\omega}_l)D\left(\boldsymbol{\omega}_l\right)\text{d}\boldsymbol{\omega}_l=L\int_{\Omega_{Po}}D_o\left(\boldsymbol{\omega}_o\right)\text{d}\boldsymbol{\omega}_o
\end{equation}

而由 Baum 等人的工作[@baum1989]可知：

\begin{equation}
  L\int_{\Omega_{Po}}D_o\left(\boldsymbol{\omega}_o\right)\text{d}\boldsymbol{\omega}_o=
  \frac{L}{2\pi}\sum^{n}_{i=1}\arccos\left(\left\langle p_i,p_j\right\rangle\right)\left\langle\frac{p_i\times p_j}{\left\lVert p_i\times p_j\right\rVert}, \begin{pmatrix}0 \\ 0 \\ 1\end{pmatrix}\right\rangle
\end{equation}

其中 $j=\left(i+1\right)\text{ mod } n$。值得注意的是，这个多边形不总是在被截断的半球上，所以实际实现时需要先对 $z>0$ 半球进行裁剪。如果某条边穿过半球边界，应该加入交点后再积分，而不是简单丢弃整条边。

### 带纹理的多边形光照解算

在上面的推导中，我们假设多边形是一个纯色光源，因此可以把 $L$ 直接从积分中提出。然而，如果多边形的辐射亮度由一个纹理决定，我们就不能这么简单地把 $L$ 从积分中提取出来了。我们可以考虑做如下分离：

\begin{equation}
  \int_{\Omega_P}L\left(\boldsymbol{\omega}_l\right)D\left(\boldsymbol{\omega}_l\right)\text{d}\boldsymbol{\omega}_l
  =
  \int_{\Omega_P}D\left(\boldsymbol{\omega}_l\right)\text{d}\boldsymbol{\omega}_l
  \dfrac
  {\int_{\Omega_P}L\left(\boldsymbol{\omega}_l\right)D\left(\boldsymbol{\omega}_l\right)\text{d}\boldsymbol{\omega}_l}
  {\int_{\Omega_P}D\left(\boldsymbol{\omega}_l\right)\text{d}\boldsymbol{\omega}_l}
\end{equation}

令：

\begin{equation}
  I_D=\int_{\Omega_P}D\left(\boldsymbol{\omega}_l\right)\text{d}\boldsymbol{\omega}_l \\
  I_L=\dfrac
  {\int_{\Omega_P}L\left(\boldsymbol{\omega}_l\right)D\left(\boldsymbol{\omega}_l\right)\text{d}\boldsymbol{\omega}_l}
  {\int_{\Omega_P}D\left(\boldsymbol{\omega}_l\right)\text{d}\boldsymbol{\omega}_l}
\end{equation}

其中 $I_D$ 可以用上一节的方法解决。而对于 $I_L$，事实上 $L\left(\boldsymbol{\omega}_l\right)$ 可以依靠纹理确认。关键在于其权重，我们考虑：

\begin{equation}
  \dfrac
  {\int_{\Omega_P}L\left(\boldsymbol{\omega}_l\right)D\left(\boldsymbol{\omega}_l\right)\text{d}\boldsymbol{\omega}_l}
  {\int_{\Omega_P}D\left(\boldsymbol{\omega}_l\right)\text{d}\boldsymbol{\omega}_l}=\int_{\Omega_P}\dfrac
  {D\left(\boldsymbol{\omega}_l\right)}
  {\int_{\Omega_P}D\left(\boldsymbol{\omega}_l\right)\text{d}\boldsymbol{\omega}_l}L\left(\boldsymbol{\omega}_l\right)\text{d}\boldsymbol{\omega}_l
\end{equation}

令 $F\left(\boldsymbol{\omega}_l\right)=\dfrac{D\left(\boldsymbol{\omega}_l\right)}{\int_{\Omega_P}D\left(\boldsymbol{\omega}_l\right)\text{d}\boldsymbol{\omega}_l}$，我们事实上关心这个 $F\left(\boldsymbol{\omega}_l\right)$ 是如何对 $L\left(\boldsymbol{\omega}_l\right)$ 进行加权的。显然 $F\left(\boldsymbol{\omega}_l\right)$ 应该具有如下性质：

- 归一化，即：
\begin{equation}
  \int_{\Omega_P}F\left(\boldsymbol{\omega}_l\right)\text{d}\boldsymbol{\omega}_l=1
\end{equation}
这是显然的。

- 低通性，这也是显然的。

因此，我们可以采用高斯滤波来近似 $F\left(\boldsymbol{\omega}\right)$。原论文中采用 $\sigma=\sqrt{\dfrac{r^2}{2A}}$ 作为高斯滤波的参数，其中 $A$ 是多边形的面积。

#### 高斯滤波参数推导

直接给出 $\sigma=\sqrt{\dfrac{r^2}{2A}}$ 未免有点不知所云，笔者初见这个公式也觉得非常神秘。因此我们需要确认这个公式是怎么来的。本质上 $F\left(\boldsymbol{\omega}_l\right)$ 是余弦瓣投影到光源纹理平面后得到的密度，其转换过程相当于一个雅可比项。假设在材质面上的密度是 $K\left(\mathbf{x}\right)$，其中 $\mathbf{x}\in\mathbb{R}^2$，我们有：

\begin{equation}
  K\left(\mathbf{x}\right)\text{d}A=D_o\left(\boldsymbol{\omega}_o\right)\text{d}\boldsymbol{\omega}_o
\end{equation}

于是 $K\left(\mathbf{x}\right)=D_o\left(\boldsymbol{\omega}_o\right)\dfrac{\text{d}\boldsymbol{\omega}_o}{\text{d}A}$，关键在于 $\dfrac{\text{d}\boldsymbol{\omega}_o}{\text{d}A}$。如[@fig:probe_cast] 我们假设着色点位于原点 $O$，材质平面位于 $z=r$。任取材质平面上一点 $X\left(x,y,r\right)$。记 $\rho=\sqrt{x^2+y^2}$，则 $XO=\sqrt{\rho^2+r^2}$。由前文讨论可知：

\begin{equation}
  \text{d}\boldsymbol{\omega}_o=\frac{\text{d}A\cos\theta}{\rho^2+r^2}
\end{equation}

而 $\cos\theta=\dfrac{r}{\sqrt{\rho^2+r^2}}$，代入得到：

\begin{equation}
  \frac{\text{d}\boldsymbol{\omega}_o}{\text{d}A}=\frac{r}{\left(\rho^2+r^2\right)^{\frac{3}{2}}}
\end{equation}

又 $D_o\left(\boldsymbol{\omega}_o\right)=\dfrac{1}{\pi}\cos\theta$，代入得到：

\begin{equation}
  K\left(\mathbf{x}\right)=\frac{r^2}{\pi\left(\rho^2+r^2\right)^{2}}
\end{equation}

![fig:probe_cast|余弦瓣在材质平面的投影|width=50%](assets/images/LTC/distribution_cast.png)

而高斯分布 $G\left(\rho\right)=\dfrac{1}{2\pi s^2}\exp\left(-\frac{\rho^2}{2s^2}\right)$。我们希望两个分布尽可能相近，所以可以在 $\rho=0$ 时令 $G\left(\rho\right)=K\left(\mathbf{x}\right)$：

\begin{equation}
  \dfrac{1}{2\pi s^2}=\dfrac{1}{\pi r^2}
\end{equation}

于是 $s=\sqrt{\dfrac{r^2}{2}}$。而 $s$ 属于几何长度，我们需要将其归一化到 UV 坐标以便于纹理采样。因此最终还要除以 $\sqrt{A}$ 作为因子。注意这里的 $\sqrt{A}$ 只是一个粗略近似。即使我们处理的多边形不一定是正方形，我们仍然使用 $\sqrt{A}$ 来规约长度。因为 LOD 对于这种近似带来的误差事实上不敏感。因此我们最终解释了文章中的式子：

\begin{equation}
  \sigma=\sqrt{\dfrac{r^2}{2A}}
\end{equation}

于是利用不同 $\sigma$ 的高斯模糊，我们就实现了对纹理的 LOD 处理。

![fig:texture_filter|不同 LOD 的预处理纹理|width=100%](assets/images/LTC/texture_filter.png)

#### 纹理采样

纹理采样，本质上就是关心在 LOD 纹理上我们应该取哪个点。关于纹理采样的部分其实我们在上一节讲解的时候就已经涉及了，只是忽略了很多细节。原论文中使用变换后分布的代表方向与光源平面的交点作为纹理查询位置，再配合前文的 $\sigma$ 选择对应的 LOD。这里直接给出论文的原图，如[@fig:distribution_projection] 所示。

![fig:distribution_projection|原论文中展示正交投影采样的图|width=50%](assets/images/LTC/distribution_projection.png)

#### 纹理边距

原文特地指出，对于 LOD 纹理应在边缘留出一定范围的空白空间，控制为边距（margin）。这么做是为了防止部分点落在纹理之外。假如没有边距，可能会导致着色结果出现明显的边缘效应，出现明显的割裂感。

## 结语

这是笔者高考结束后啃的第一篇图形学论文。受益匪浅。LTC 方法巧妙，其近似变换的思想十分值得借鉴。如果读者有任何问题或者批评欢迎随时交流和指出。过几天会用 [EasyGPU](https://github.com/EasyGPU/EasyGPU) 的 Graphics Pipeline 和自动可微功能实现一遍，更深刻地体会这个奇妙的方法。

感谢你的阅读。
