# SAM 모델 체크포인트

이 폴더에 SAM 체크포인트 파일이 필요합니다 (총 ~4GB).
파일 크기 문제로 삭제되었으며, SAM 기능 사용 시 재설치해야 합니다.

## 재설치 방법

### MobileSAM (경량, 권장)
```bash
pip install git+https://github.com/ChaoningZhang/MobileSAM.git
```
체크포인트는 `src/sam/client.py` 실행 시 자동 다운로드됩니다.

### 수동 다운로드
아래 파일을 이 폴더에 저장:
- `mobile_sam.pt` (39MB) — MobileSAM
- `sam_vit_b_01ec64.pth` (358MB) — SAM ViT-B
- `sam_vit_l_0b3195.pth` (1.2GB) — SAM ViT-L
- `sam_vit_h_4b8939.pth` (2.4GB) — SAM ViT-H

다운로드: https://github.com/facebookresearch/segment-anything#model-checkpoints
