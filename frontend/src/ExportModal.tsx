import { useEffect, useState } from 'react';
import { useLogto } from '@logto/react';
import {
  exportPostZip,
  fetchImagePolishStatus,
  fetchPolishedImages,
  startImagePolish,
  LoginRequiredError,
  SubscriptionRequiredError,
  Post,
} from './api';
import { trackImagePolish, trackZipDownload } from './analytics';

const EXPORT_TIP = '润色图片后导出zip';

const DEFAULT_POLISH_PROMPT =
  '在严格保持原图主体、场景内容、人物/物体身份特征、整体氛围不变的前提下，做高质量修复与增强：细节更清晰、纹理更真实、边缘更干净，自然锐化、轻微降噪、提高微对比度与层次；轻微优化构图与视线引导（更平衡、更舒适），但不新增/不删除关键元素、不改变主体形状与比例；色彩自然耐看；画面干净通透、高清、写实、质感高级。去除水印';

const pendingPolishTasks = new Map<string, { requestId: number; prompt: string }>();

type ImageState = {
  originalUrl: string;
  currentUrl: string;
  usingPolished: boolean;
  promptOpen: boolean;
  prompt: string;
  polishing: boolean;
  polishRequestId?: number;
  error: string;
};

function initImageStates(images: string[]): ImageState[] {
  return images.map((url) => ({
    originalUrl: url,
    currentUrl: url,
    usingPolished: false,
    promptOpen: false,
    prompt: DEFAULT_POLISH_PROMPT,
    polishing: false,
    polishRequestId: undefined,
    error: '',
  }));
}

function polishTaskKey(postId: number, originalUrl: string): string {
  return `${postId}:${originalUrl}`;
}

export default function ExportModal({
  post,
  onClose,
  onPaywall,
  onLoginRequired,
}: {
  post: Post;
  onClose: () => void;
  onPaywall?: (error: SubscriptionRequiredError) => void;
  onLoginRequired?: () => void;
}) {
  const { isAuthenticated } = useLogto();
  const [images, setImages] = useState<ImageState[]>(() =>
    initImageStates(post.images).map((item) => {
      const pending = pendingPolishTasks.get(polishTaskKey(post.id, item.originalUrl));
      if (!pending) return item;
      return {
        ...item,
        prompt: pending.prompt,
        polishing: true,
        polishRequestId: pending.requestId,
      };
    }),
  );
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState('');

  useEffect(() => {
    let cancelled = false;
    void fetchPolishedImages(post.id)
      .then((records) => {
        if (cancelled || records.length === 0) return;
        const byOriginal = new Map(records.map((record) => [record.original_url, record]));
        setImages((current) =>
          current.map((item) => {
            const record = byOriginal.get(item.originalUrl);
            if (!record) return item;
            return {
              ...item,
              currentUrl: record.polished_url,
              usingPolished: true,
              prompt: record.prompt,
            };
          }),
        );
      })
      .catch(() => {
        /* 历史记录加载失败时静默忽略，不影响正常导出流程 */
      });
    return () => {
      cancelled = true;
    };
  }, [post.id]);

  useEffect(() => {
    const active = images.filter((item) => item.polishing && item.polishRequestId);
    if (active.length === 0) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      active.forEach((item) => {
        if (!item.polishRequestId) return;
        void fetchImagePolishStatus(item.polishRequestId)
          .then((status) => {
            if (cancelled) return;
            if (status.status === 'success' && status.polished_image_url) {
              setImages((current) =>
                current.map((currentItem) =>
                  currentItem.polishRequestId === item.polishRequestId
                    ? {
                        ...currentItem,
                        currentUrl: status.polished_image_url!,
                        usingPolished: true,
                        polishing: false,
                        polishRequestId: undefined,
                        promptOpen: false,
                        error: '',
                      }
                    : currentItem,
                ),
              );
              pendingPolishTasks.delete(polishTaskKey(post.id, item.originalUrl));
            } else if (status.status === 'failed') {
              setImages((current) =>
                current.map((currentItem) =>
                  currentItem.polishRequestId === item.polishRequestId
                    ? {
                        ...currentItem,
                        polishing: false,
                        polishRequestId: undefined,
                        error: status.error_message || '润色失败，请重试',
                      }
                    : currentItem,
                ),
              );
              pendingPolishTasks.delete(polishTaskKey(post.id, item.originalUrl));
            }
          })
          .catch(() => {
            /* 轮询失败可能是瞬时网络问题，下一轮继续尝试 */
          });
      });
    }, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [images, post.id]);

  function patchImage(index: number, patch: Partial<ImageState>) {
    setImages((current) => current.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  }

  function togglePromptBox(index: number) {
    if (!isAuthenticated) {
      onLoginRequired?.();
      return;
    }
    patchImage(index, { promptOpen: !images[index].promptOpen, error: '' });
  }

  async function runPolish(index: number) {
    const target = images[index];
    if (!isAuthenticated) {
      onLoginRequired?.();
      return;
    }
    if (!target.prompt.trim()) {
      patchImage(index, { error: '请输入润色提示词' });
      return;
    }
    patchImage(index, { polishing: true, error: '' });
    trackImagePolish({ post_id: post.id });
    try {
      const status = await startImagePolish(target.originalUrl, target.prompt.trim(), post.id);
      if (status.status === 'success' && status.polished_image_url) {
        pendingPolishTasks.delete(polishTaskKey(post.id, target.originalUrl));
        patchImage(index, {
          currentUrl: status.polished_image_url,
          usingPolished: true,
          polishing: false,
          polishRequestId: undefined,
          promptOpen: false,
        });
        return;
      }
      if (status.status === 'failed') {
        pendingPolishTasks.delete(polishTaskKey(post.id, target.originalUrl));
        patchImage(index, {
          polishing: false,
          polishRequestId: undefined,
          error: status.error_message || '润色失败，请重试',
        });
        return;
      }
      if (status.polish_request_id) {
        pendingPolishTasks.set(polishTaskKey(post.id, target.originalUrl), {
          requestId: status.polish_request_id,
          prompt: target.prompt.trim(),
        });
      }
      patchImage(index, { polishing: true, polishRequestId: status.polish_request_id, error: '' });
    } catch (err) {
      pendingPolishTasks.delete(polishTaskKey(post.id, target.originalUrl));
      if (err instanceof SubscriptionRequiredError) {
        patchImage(index, {
          polishing: false,
          polishRequestId: undefined,
          error: '',
        });
        onPaywall?.(err);
        return;
      }
      if (err instanceof LoginRequiredError) {
        patchImage(index, {
          polishing: false,
          polishRequestId: undefined,
          error: '',
        });
        onLoginRequired?.();
        return;
      }
      patchImage(index, {
        polishing: false,
        polishRequestId: undefined,
        error: err instanceof Error ? err.message : '润色失败，请重试',
      });
    }
  }

  function revertToOriginal(index: number) {
    patchImage(index, { currentUrl: images[index].originalUrl, usingPolished: false });
  }

  async function runExport() {
    setExporting(true);
    setExportError('');
    try {
      const finalUrls = images.map((item) => item.currentUrl);
      const blob = await exportPostZip(post.id, finalUrls);
      trackZipDownload({ post_id: post.id, image_count: finalUrls.length });
      const downloadUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = `${post.title.slice(0, 30) || 'xhs_note'}.zip`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(downloadUrl);
      onClose();
    } catch (err) {
      setExportError(err instanceof Error ? err.message : '导出失败，请重试');
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="export-overlay" onClick={onClose}>
      <div className="export-modal" onClick={(event) => event.stopPropagation()}>
        <div className="export-modal-head">
          <h3>{EXPORT_TIP}</h3>
          <button className="export-modal-close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </div>
        <p className="export-modal-hint">
          将本条内容的标题、正文、标签和图片打包下载。也可以对任意图片使用
          <span className="pro-badge">PRO · AI润色</span>
          后再导出为 ZIP。
        </p>

        <div className="export-image-grid">
          {images.map((item, index) => (
            <div className="export-image-card" key={item.originalUrl}>
              <div className="export-image-preview">
                <img src={item.currentUrl} alt="" />
                {item.usingPolished && <span className="export-image-tag">已润色</span>}
                {item.polishing && (
                  <div className="export-image-loading">
                    <span className="generation-spinner" aria-hidden="true" />
                    润色中…
                  </div>
                )}
              </div>
              <div className="export-image-actions">
                <button
                  type="button"
                  className="pro-polish-btn"
                  onClick={() => togglePromptBox(index)}
                  disabled={item.polishing}
                >
                  ✨ PRO · AI润色
                </button>
                {item.usingPolished && (
                  <button type="button" className="ghost export-revert-btn" onClick={() => revertToOriginal(index)}>
                    还原原图
                  </button>
                )}
              </div>
              {item.promptOpen && (
                <div className="export-prompt-box">
                  <textarea
                    value={item.prompt}
                    onChange={(event) => patchImage(index, { prompt: event.target.value })}
                    placeholder="描述你想要的润色效果…"
                    rows={3}
                  />
                  {item.error && <p className="export-prompt-error">{item.error}</p>}
                  <div className="export-prompt-buttons">
                    <button type="button" className="ghost" onClick={() => togglePromptBox(index)}>
                      取消
                    </button>
                    <button
                      type="button"
                      className="primary"
                      onClick={() => runPolish(index)}
                      disabled={item.polishing}
                    >
                      {item.polishing ? '生成中…' : '开始润色'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>

        {exportError && <p className="banner error">{exportError}</p>}

        <div className="export-modal-footer">
          <button className="ghost" onClick={onClose}>
            取消
          </button>
          <button className="primary" onClick={runExport} disabled={exporting}>
            {exporting ? '正在打包…' : '导出zip包'}
          </button>
        </div>
      </div>
    </div>
  );
}
