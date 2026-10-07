---
title: "ImageKit Original Delivery Verification"
tags: [pinterest, imagekit]
status: active
created: 2026-09-17
---

The first pilot asset uploaded successfully, but default CDN optimization changed its bytes. ImageKit documents `tr:orig-true` to deliver the original file unchanged: https://imagekit.io/docs/core-delivery-features

The same uploaded asset with `tr:orig-true` passed public image decoding, 1024x1536 dimensions, and SHA-256 comparison against the generated local PNG. Evidence: `batches/elevenlabs-pilot/original-media-check.json`. No account setting changed and no duplicate upload was needed.
