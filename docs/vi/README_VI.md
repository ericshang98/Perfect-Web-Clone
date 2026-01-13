# Nexting

<div align="center">

**Công Cụ Clone Web Được Hỗ Trợ Bởi AI — Xây Dựng Với Claude Agent SDK**

*Claude Code cho việc clone web. Một AI agent chuyên biệt với hơn 40 công cụ chuyên dụng.*

[English](../../README.md) | [中文](../cn/README_CN.md) | [日本語](../ja/README_JA.md) | [한국어](../ko/README_KO.md) | [Español](../es/README_ES.md) | [Português](../pt/README_PT.md) | [Deutsch](../de/README_DE.md) | [Français](../fr/README_FR.md) | Tiếng Việt

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Next.js](https://img.shields.io/badge/Next.js-15.x-black)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19.x-61dafb)](https://react.dev/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Playwright-1.49+-2EAD33)](https://playwright.dev/)
[![Claude](https://img.shields.io/badge/Claude-Anthropic-cc785c)](https://anthropic.com/)

</div>

**Một AI agent thực sự** — không chỉ là wrapper quanh một LLM. Hợp tác đa agent với các công cụ thực, vòng lặp tự sửa lỗi, và môi trường sandbox hoàn chỉnh để xây dựng code sẵn sàng cho production từ đầu.

Các công cụ khác đoán code từ ảnh chụp màn hình. Chúng tôi trích xuất **code thực** — DOM, styles, components, interactions. **Clone pixel-perfect** mà các công cụ dựa trên ảnh chụp màn hình đơn giản không thể đạt được.

https://github.com/user-attachments/assets/248af639-20d9-45a8-ad0a-660a04a17b68

## Kiến Trúc Multi-Agent Mã Nguồn Mở

**Toàn bộ hệ thống multi-agent là mã nguồn mở.** Học hỏi từ nó, sử dụng nó, xây dựng trên nó.

### Tại Sao Multi-Agent?

Các phương pháp AI truyền thống với một model đơn gặp giới hạn với các tác vụ phức tạp. Một model cố gắng xử lý mọi thứ dẫn đến:
- Tràn context window trên các trang lớn
- Ảo giác khi xử lý quá nhiều trách nhiệm
- Xử lý tuần tự chậm

Giải pháp của chúng tôi: **Các agent chuyên biệt làm việc song song**, mỗi agent tập trung vào điều họ làm tốt nhất.

### Tại Sao Không Dùng Cursor / Claude Code / Copilot?

<p align="center">
  <img src="https://img.shields.io/badge/Cursor-000000?style=for-the-badge&logo=cursor&logoColor=white" alt="Cursor" />
  <img src="https://img.shields.io/badge/Claude_Code-cc785c?style=for-the-badge&logo=anthropic&logoColor=white" alt="Claude Code" />
  <img src="https://img.shields.io/badge/GitHub_Copilot-000000?style=for-the-badge&logo=githubcopilot&logoColor=white" alt="GitHub Copilot" />
  <span style="margin: 0 10px;">vs</span>
  <img src="https://img.shields.io/badge/Nexting-8B5CF6?style=for-the-badge" alt="Nexting" />
</p>

Chúng tôi đã thử. Ngay cả với **JSON trích xuất hoàn chỉnh** — cây DOM đầy đủ, tất cả CSS rules, mọi asset URL — các công cụ single-model vẫn gặp khó khăn:

| Thách Thức | <img src="https://img.shields.io/badge/-Cursor-000?style=flat-square&logo=cursor" /> <img src="https://img.shields.io/badge/-Claude_Code-cc785c?style=flat-square&logo=anthropic" /> <img src="https://img.shields.io/badge/-Copilot-000?style=flat-square&logo=githubcopilot" /> | <img src="https://img.shields.io/badge/-Nexting-8B5CF6?style=flat-square" /> Multi-Agent |
|------------|-------------------------------|---------------------|
| **Cây DOM 50,000+ dòng** | ❌ Tràn context, cắt bớt phần quan trọng | ✅ DOM Agent xử lý theo chunks |
| **3,000+ CSS rules** | ❌ Mất specificity, bỏ lỡ variables | ✅ Style Agent xử lý CSS riêng |
| **Phát hiện components** | ❌ Đoán ranh giới, tạo monoliths | ✅ Agent chuyên dụng nhận diện patterns |
| **Responsive breakpoints** | ❌ Thường hardcode một viewport | ✅ Trích xuất tất cả media queries |
| **Trạng thái hover/animation** | ❌ Không thể thấy, không thể tái tạo | ✅ Browser automation capture tất cả |
| **Chất lượng output** | ❌ Xấp xỉ "gần đủ" | ✅ Pixel-perfect, sẵn sàng production |

> **Vấn đề cốt lõi**: JSON trích xuất 200KB vượt quá giới hạn context thực tế. Ngay cả khi vừa, model không thể duy trì sự nhất quán qua DOM→CSS→Components→Code. Mỗi bước cần sự chú ý tập trung.

### Pattern Agent + Tools + Sandbox

```
┌─────────────────────────────────────────────────────────┐
│                    Hệ Thống Multi-Agent                  │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ DOM Agent   │  │ Style Agent │  │ Code Agent  │     │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │
│         │                │                │             │
│         ▼                ▼                ▼             │
│  ┌─────────────────────────────────────────────────┐   │
│  │                   Công Cụ                        │   │
│  │  • Thao Tác File  • Phân Tích Code              │   │
│  │  • Điều Khiển Browser  • Gọi API                │   │
│  └─────────────────────────────────────────────────┘   │
│                         │                               │
│                         ▼                               │
│  ┌─────────────────────────────────────────────────┐   │
│  │              Sandbox (BoxLite)                   │   │
│  │  Môi trường thực thi cô lập cho việc sinh code │   │
│  │  an toàn, testing và preview                    │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

Pattern này — **Agent + Tools + Sandbox** — có thể tái sử dụng cho bất kỳ sản phẩm AI agent nào:

| Component | Mục Đích | Trong Nexting |
|-----------|----------|---------------|
| **Agents** | AI workers chuyên biệt với trách nhiệm tập trung | Agents DOM, Style, Component, Code |
| **Tools** | Khả năng mà agents có thể gọi | File I/O, Browser automation, API calls |
| **Sandbox** | Môi trường thực thi an toàn | [BoxLite](https://github.com/boxlite-ai/boxlite) - Embedded micro-VM runtime |

### Liên Hệ Với Tôi

Đang xây dựng gì đó với kiến trúc này? Có câu hỏi? Liên hệ:

[![Twitter](https://img.shields.io/badge/Twitter-@ericshang98-1DA1F2?style=flat&logo=twitter)](https://twitter.com/ericshang98)
[![GitHub](https://img.shields.io/badge/GitHub-ericshang98-181717?style=flat&logo=github)](https://github.com/ericshang98)
[![Discord](https://img.shields.io/badge/Discord-Tham_Gia_Cộng_Đồng-5865F2?style=flat&logo=discord&logoColor=white)](https://discord.gg/HJURzJq3y5)

---

## Bắt Đầu Nhanh

### Yêu Cầu

- Python 3.11+
- Node.js 18+
- Anthropic API Key

### Bắt Đầu Nhanh

1. **Clone repository**

```bash
git clone https://github.com/ericshang98/perfect-web-clone.git
cd perfect-web-clone
```

2. **Cài Đặt Backend**

```bash
cd backend

# Copy file môi trường và thêm API key của bạn
cp ../.env.example .env
# Chỉnh sửa .env và thêm ANTHROPIC_API_KEY của bạn

# Khởi động server (tự động cài đặt dependencies)
sh start.sh
```

3. **Cài Đặt Frontend**

```bash
cd frontend

# Cài đặt dependencies
npm install

# Cấu hình môi trường (tùy chọn)
cp ../.env.example .env.local

# Khởi động development server
npm run dev
```

4. **Mở Ứng Dụng**

Truy cập [http://localhost:3000](http://localhost:3000) trong trình duyệt của bạn.

## Giấy Phép

Dự án này được cấp phép theo MIT License - xem file [LICENSE](../../LICENSE) để biết chi tiết.

---

<div align="center">

**[Nexting](https://github.com/ericshang98/perfect-web-clone)** - Trích xuất code thực, không phải phỏng đoán.

Được tạo với ❤️ bởi [Eric Shang](https://github.com/ericshang98)

</div>
