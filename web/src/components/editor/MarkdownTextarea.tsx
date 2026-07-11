import { useEffect, useRef } from 'react';
import { setEditorEl } from '../../lib/insert';
import { schedulePreview } from '../../lib/previewBus';
import { handleHotkey } from './toolbarConfig';
import { lsStore } from '../../lib/lsStore';

/* НЕКОНТРОЛИРУЕМЫЙ textarea — принципиально: контролируемый React-инпут
   уничтожил бы нативную историю Ctrl+Z, на которой держатся панель,
   сниппеты и AI-вставка (все они идут через execCommand('insertText')).
   Текст зеркалится в localStorage на input, как в editor.html. */
export default function MarkdownTextarea() {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setEditorEl(ref.current);
    return () => setEditorEl(null);
  }, []);

  return (
    <textarea
      id="md"
      ref={ref}
      defaultValue={lsStore.get('draft') || ''}
      placeholder={'# Заголовок поста\n\nНачните писать — предпросмотр обновляется сам…'}
      autoCapitalize="sentences"
      spellCheck
      onInput={(e) => {
        lsStore.set('draft', e.currentTarget.value);
        schedulePreview();
      }}
      onKeyDown={handleHotkey}
    />
  );
}
