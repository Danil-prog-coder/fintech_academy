import { Info, Star } from 'lucide-react';
import { useState } from 'react';

import {
  ApprovalStatus,
  toAttachment,
  useGetDocumentVersionsQuery,
  type DocumentFile,
} from '@/entities/document';
import { draftAttachmentRemoved, draftAttachmentSet, selectDraft } from '@/entities/draft';
import { cx } from '@/shared/lib/cx';
import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { showToast } from '@/shared/lib/toast';
import { Badge, Button, Checkbox, FileTypeIcon, Modal, Skeleton } from '@/shared/ui';

import styles from './VersionPickerModal.module.css';
import { selectVersionPickerLetterId, versionPickerClosed } from '../../model/versionPickerSlice';

/** Выбор версии вложения: рекомендуемая (согласованная) и альтернативы. */
export const VersionPickerModal = () => {
  const dispatch = useAppDispatch();
  const letterId = useAppSelector(selectVersionPickerLetterId);
  const draft = useAppSelector((state) => selectDraft(state, letterId));
  const { data: versions, isLoading } = useGetDocumentVersionsQuery('presentation', {
    skip: !letterId,
  });
  const [exclude, setExclude] = useState(false);

  const close = () => {
    if (letterId && exclude) {
      dispatch(draftAttachmentRemoved({ letterId }));
      showToast('Предложенный файл исключён из ответа');
    }
    setExclude(false);
    dispatch(versionPickerClosed());
  };

  const choose = (document: DocumentFile) => {
    if (!letterId) {
      return;
    }
    dispatch(
      draftAttachmentSet({
        letterId,
        attachment: toAttachment(document, {
          externalRecipient: draft?.to.some((recipient) => recipient.external) ?? false,
        }),
      }),
    );
    showToast(`Вложение заменено: ${document.name}`, 'success');
    setExclude(false);
    dispatch(versionPickerClosed());
  };

  const versionsToShow = (versions ?? []).filter((item) => item.id !== 'doc-pres-final');

  return (
    <Modal
      open={Boolean(letterId)}
      onClose={close}
      title="Выбрать версию"
      description="Найдено несколько версий этого файла. Выберите подходящую."
      footer={
        <>
          <Checkbox
            checked={exclude}
            onChange={setExclude}
            label="Исключить предложенный файл"
            description="Этот файл не будет предлагаться для замены."
          />
          <Button onClick={close}>Закрыть</Button>
        </>
      }
    >
      {isLoading ? (
        <div className={styles.loading}>
          <Skeleton height={120} />
          <Skeleton height={120} />
        </div>
      ) : (
        versionsToShow.map((document) => {
          const recommended = document.approval === 'approved';
          const current = draft?.attachment?.documentId === document.id;
          return (
            <article
              key={document.id}
              className={cx(styles.version, recommended && styles.recommended)}
            >
              <div className={styles.file}>
                <FileTypeIcon type={document.fileType} size="lg" />
                <div className={styles.info}>
                  <p className={styles.name}>{document.name}</p>
                  <ApprovalStatus
                    approval={document.approval}
                    text={document.updatedLabel}
                    clock={!recommended}
                  />
                  <p className={styles.source}>Источник: {document.source}</p>
                  <div className={styles.actions}>
                    <Button
                      onClick={() => {
                        showToast(`Открываем «${document.name}» с проверкой доступа`);
                      }}
                    >
                      Открыть
                    </Button>
                    <Button
                      variant={recommended ? 'primary' : 'soft'}
                      disabled={current}
                      onClick={() => {
                        choose(document);
                      }}
                    >
                      {current ? 'Выбрано' : recommended ? 'Выбрать' : 'Заменить'}
                    </Button>
                  </div>
                </div>
              </div>
              <div className={styles.reason}>
                {recommended ? (
                  <Badge tone="accent" icon={<Star size={14} fill="currentColor" />}>
                    Рекомендуем
                  </Badge>
                ) : (
                  <Badge tone="neutral" icon={<Info size={14} />}>
                    Согласование не найдено
                  </Badge>
                )}
                <p className={styles.reasonText}>{document.approvalNote}</p>
              </div>
            </article>
          );
        })
      )}
    </Modal>
  );
};
