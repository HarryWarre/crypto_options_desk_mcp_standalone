#!/usr/bin/env bash
# ==============================================================================
# Google Drive 5TB Cold Storage Sync Utility via Rclone
#
# Usage:
#   ./scripts/sync_gdrive.sh push   # Upload local Parquet datasets to Google Drive
#   ./scripts/sync_gdrive.sh pull   # Download Parquet datasets from Google Drive
#   ./scripts/sync_gdrive.sh status # Show current remote datasets on Google Drive
# ==============================================================================

set -euo pipefail

REMOTE_NAME="gdrive"
REMOTE_PATH="gdrive:OptionsData/deribit_parquet"
LOCAL_PATH="./data/deribit_parquet"

function check_rclone() {
    if ! command -v rclone &> /dev/null; then
        echo "❌ rclone chưa được cài đặt."
        echo "💡 Để cài đặt trên macOS: brew install rclone"
        echo "💡 Sau đó cấu hình Google Drive bằng: rclone config (chọn loại Google Drive)"
        exit 1
    fi
}

case "${1:-status}" in
    push)
        check_rclone
        echo "🚀 Đang đẩy dữ liệu Parquet lên Google Drive (${REMOTE_PATH})..."
        rclone sync "$LOCAL_PATH" "$REMOTE_PATH" \
            --progress \
            --transfers 4 \
            --checkers 8 \
            --fast-list
        echo "✅ Đồng bộ lên Google Drive hoàn tất!"
        ;;
    pull)
        check_rclone
        echo "📥 Đang tải dữ liệu Parquet từ Google Drive về ${LOCAL_PATH}..."
        mkdir -p "$LOCAL_PATH"
        rclone sync "$REMOTE_PATH" "$LOCAL_PATH" \
            --progress \
            --transfers 4 \
            --checkers 8 \
            --fast-list
        echo "✅ Tải về hoàn tất!"
        ;;
    status)
        check_rclone
        echo "📊 Danh sách dữ liệu trên Google Drive (${REMOTE_PATH}):"
        rclone lsd "$REMOTE_PATH" 2>/dev/null || echo "Thư mục trống hoặc chưa có kết nối."
        ;;
    *)
        echo "Cách dùng: $0 {push|pull|status}"
        exit 1
        ;;
esac

