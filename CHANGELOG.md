# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Chat messages accept OpenAI `text` + `image_url` content parts. The gateway
  records a 3NF `image_content_catalog` (`image_payload` / `image_placement` /
  `image_recognition_event`) so an invoice PNG stays next to
  `Please pay invoice 1042`. Raw base64 is hashed, not stored. Next action:
  send the figure as `data:image/png;base64,...` or `https://...` and read
  `orchestration.image_content_catalog` to find it.

### References

- Faysse, M., Sibille, H., Wu, T., Omrani, B., Viaud, G., Hudelot, C., &
  Colombo, P. (2024). *ColPali: Efficient document retrieval with vision
  language models* (arXiv:2407.01449). arXiv.
  https://doi.org/10.48550/arXiv.2407.01449
- Xu, Y., Li, M., Cui, L., Huang, S., Wei, F., & Zhou, M. (2020). LayoutLM:
  Pre-training of text and layout for document image understanding. In
  *Proceedings of the 26th ACM SIGKDD International Conference on Knowledge
  Discovery & Data Mining* (pp. 1192–1200). Association for Computing
  Machinery. https://doi.org/10.1145/3394486.3403172
- Masinter, L. (1998). *The "data" URL scheme* (RFC 2397). Internet
  Engineering Task Force. https://doi.org/10.17487/RFC2397
