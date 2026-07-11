import { useToast } from '../store/toast';

export default function Toast() {
  const { text, isError, visible } = useToast();
  return (
    <div id="toast" className={visible ? 'show' + (isError ? ' err' : '') : ''}>
      {text}
    </div>
  );
}
