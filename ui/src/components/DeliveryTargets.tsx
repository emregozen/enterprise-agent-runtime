import { Link } from "react-router-dom";
import { Select } from "./Select";
import { copy } from "../lib/copy";

export const DEFAULT_SUBJECT = "{{agent_name}} – {{run_date}}";

export type DraftTarget = {
  channel: string;
  toText: string;
  ccText: string;
  subject: string;
  when: "success" | "failure" | "always";
  content: "inline" | "attachment" | "artifacts" | "link";
  attachment: "md" | "html";
};

export type ChannelChoice = { name: string; kind: string; enabled: boolean; allow_domains?: string[] };

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function blankTarget(channel = ""): DraftTarget {
  return {
    channel,
    toText: "",
    ccText: "",
    subject: DEFAULT_SUBJECT,
    when: "success",
    content: "inline",
    attachment: "html",
  };
}

export function draftsFromSpec(spec: Record<string, unknown> | null): DraftTarget[] {
  const inner = (spec?.spec as { delivery?: Record<string, unknown>[] } | undefined)?.delivery || [];
  return inner.map((item) => ({
    channel: String(item.channel || ""),
    toText: Array.isArray(item.to) ? item.to.join(", ") : "",
    ccText: Array.isArray(item.cc) ? item.cc.join(", ") : "",
    subject: String(item.subject || DEFAULT_SUBJECT),
    when: item.when === "failure" || item.when === "always" ? item.when : "success",
    content: item.content === "attachment" || item.content === "artifacts" || item.content === "link" ? item.content : "inline",
    attachment: item.attachment === "md" ? "md" : "html",
  }));
}

export function parseAddresses(value: string): string[] {
  const found: string[] = [];
  for (const part of value.split(/[,;]+/)) {
    const address = part.trim().toLowerCase();
    if (address && !found.includes(address)) found.push(address);
  }
  return found;
}

export function deliveryReady(targets: DraftTarget[]): boolean {
  return targets.every((target) => target.channel && parseAddresses(target.toText).length > 0 && parseAddresses(target.toText).every((item) => EMAIL.test(item)) && parseAddresses(target.ccText).every((item) => EMAIL.test(item)));
}

export function writeDelivery(spec: Record<string, unknown>, targets: DraftTarget[]): Record<string, unknown> {
  const next = structuredClone(spec);
  const inner = (next.spec as Record<string, unknown>) || {};
  inner.delivery = targets.map((target) => ({
    channel: target.channel,
    to: parseAddresses(target.toText),
    cc: parseAddresses(target.ccText),
    subject: target.subject.trim() || DEFAULT_SUBJECT,
    when: target.when,
    content: target.content,
    attachment: target.attachment,
  }));
  next.spec = inner;
  return next;
}

export function DeliveryEditor({
  channels,
  targets,
  onChange,
}: {
  channels: ChannelChoice[];
  targets: DraftTarget[];
  onChange: (next: DraftTarget[]) => void;
}) {
  const enabled = channels.filter((channel) => channel.enabled);
  const options = enabled.map((channel) => ({
    value: channel.name,
    label: channel.name,
    description: channel.kind === "http" ? copy.httpApi : copy.smtp,
  }));
  function patch(index: number, partial: Partial<DraftTarget>) {
    onChange(targets.map((target, item) => (item === index ? { ...target, ...partial } : target)));
  }
  return (
    <div>
      <p>{copy.deliveryFixed}</p>
      {targets.length === 0 && <p>{copy.deliveryNone}</p>}
      {enabled.length === 0 && (
        <p>{copy.noChannelYet} <Link to="/delivery">{copy.openChannels}</Link></p>
      )}
      {targets.map((target, index) => (
        <div className="grid-2" key={index} style={{ marginTop: 12 }}>
          <label className="field">{copy.channel}
            <Select
              ariaLabel={`${copy.channel} ${index + 1}`}
              value={target.channel}
              onChange={(channel) => patch(index, { channel })}
              placeholder={copy.select}
              options={options.some((item) => item.value === target.channel) || !target.channel ? options : [{ value: target.channel, label: target.channel, description: copy.failed }, ...options]}
            />
          </label>
          <label className="field">{copy.sendWhen}
            <Select
              ariaLabel={`${copy.sendWhen} ${index + 1}`}
              value={target.when}
              onChange={(when) => patch(index, { when: when as DraftTarget["when"] })}
              options={[
                { value: "success", label: copy.onSuccess },
                { value: "failure", label: copy.onFailure },
                { value: "always", label: copy.always },
              ]}
            />
          </label>
          <label className="field">{copy.recipients}
            <input aria-label={`${copy.recipients} ${index + 1}`} value={target.toText} placeholder="finance@company.example" onChange={(event) => patch(index, { toText: event.target.value })} />
          </label>
          <label className="field">{copy.cc}
            <input aria-label={`${copy.cc} ${index + 1}`} value={target.ccText} onChange={(event) => patch(index, { ccText: event.target.value })} />
          </label>
          <label className="field" style={{ gridColumn: "1 / -1" }}>{copy.subjectTemplate}
            <input aria-label={`${copy.subjectTemplate} ${index + 1}`} value={target.subject} onChange={(event) => patch(index, { subject: event.target.value })} />
          </label>
          <label className="field">{copy.sendContent}
            <Select
              ariaLabel={`${copy.sendContent} ${index + 1}`}
              value={target.content}
              onChange={(content) => patch(index, { content: content as DraftTarget["content"] })}
              options={[
                { value: "inline", label: copy.inlineHtml },
                { value: "attachment", label: copy.reportAttachment },
                { value: "artifacts", label: copy.artifactAttachments },
                { value: "link", label: copy.linkOnly },
              ]}
            />
          </label>
          {target.content === "attachment" && (
            <label className="field">{copy.attachmentFormat}
              <Select
                ariaLabel={`${copy.attachmentFormat} ${index + 1}`}
                value={target.attachment}
                onChange={(attachment) => patch(index, { attachment: attachment as DraftTarget["attachment"] })}
                options={[
                  { value: "html", label: copy.htmlFile },
                  { value: "md", label: copy.markdownFile },
                ]}
              />
            </label>
          )}
          <div className="field">
            <span>&nbsp;</span>
            <button className="btn-ghost" type="button" onClick={() => onChange(targets.filter((_, item) => item !== index))}>{copy.removeRecipient}</button>
          </div>
        </div>
      ))}
      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn-ghost" type="button" onClick={() => onChange([...targets, blankTarget(enabled.length === 1 ? enabled[0].name : "")])}>{copy.addRecipient}</button>
      </div>
    </div>
  );
}
