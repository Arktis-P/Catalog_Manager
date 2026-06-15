interface GenerationPromptPipelineProps {
  prefix: string;
  suffix: string;
  wildcardToken: string;
  onPrefixChange?: (value: string) => void;
  onSuffixChange?: (value: string) => void;
  readOnly?: boolean;
}

export function GenerationPromptPipeline({
  prefix,
  suffix,
  wildcardToken,
  onPrefixChange,
  onSuffixChange,
  readOnly = false,
}: GenerationPromptPipelineProps) {
  const editable = !readOnly && onPrefixChange && onSuffixChange;

  return (
    <div className="generation-prompt-pipeline">
      <div className="generation-prompt-pipeline__cell">
        <span className="generation-prompt-pipeline__label">Prefix</span>
        {editable ? (
          <textarea
            className="generation-prompt-pipeline__input"
            value={prefix}
            rows={3}
            onChange={(event) => onPrefixChange(event.target.value)}
          />
        ) : (
          <pre className="generation-prompt-pipeline__input generation-prompt-pipeline__readonly">{prefix}</pre>
        )}
      </div>
      <div className="generation-prompt-pipeline__wildcard">
        <span className="generation-prompt-pipeline__label">Wildcard</span>
        <code className="generation-prompt-pipeline__wildcard-token">{wildcardToken}</code>
      </div>
      <div className="generation-prompt-pipeline__cell">
        <span className="generation-prompt-pipeline__label">Suffix</span>
        {editable ? (
          <textarea
            className="generation-prompt-pipeline__input"
            value={suffix}
            rows={3}
            onChange={(event) => onSuffixChange(event.target.value)}
          />
        ) : (
          <pre className="generation-prompt-pipeline__input generation-prompt-pipeline__readonly">{suffix}</pre>
        )}
      </div>
    </div>
  );
}

function wildcardTokenForSeries(seriesTag: string | undefined): string {
  if (!seriesTag) {
    return "__*catalogue_manager/{series}_xxxxxxxx_characters__";
  }
  return `__*catalogue_manager/${seriesTag}_xxxxxxxx_characters__`;
}

export function wildcardTokenFromQueue(queueId: string): string {
  return `__*catalogue_manager/${queueId}_characters__`;
}

export { wildcardTokenForSeries };
