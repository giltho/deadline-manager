import { Action, ActionPanel, Form, showToast, Toast, useNavigation } from "@raycast/api";
import { useForm, FormValidation, withAccessToken, usePromise } from "@raycast/utils";
import { createDeadline, getAllMembers, type GuildMember } from "./api";
import { authorize } from "./oauth";

interface FormValues {
  title: string;
  due_date: string;
  description: string;
  member_ids: string[];
}

interface Props {
  onCreated?: () => void;
}

function CreateDeadline({ onCreated }: Props) {
  const { pop } = useNavigation();

  // Load all guild members on mount so Form.TagPicker can filter them client-side.
  // Form.TagPicker has no onSearchTextChange — all filtering is client-side only.
  const { isLoading: isSearching, data: memberResults } = usePromise(getAllMembers);

  const { handleSubmit, itemProps } = useForm<FormValues>({
    initialValues: {
      member_ids: [],
    },
    async onSubmit(vals) {
      const toast = await showToast({ style: Toast.Style.Animated, title: "Creating deadline..." });
      try {
        await createDeadline({
          title: vals.title.trim(),
          due_date: vals.due_date.trim(),
          description: vals.description.trim() || undefined,
          member_ids: vals.member_ids,
        });
        toast.style = Toast.Style.Success;
        toast.title = "Deadline created";
        onCreated?.();
        pop();
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        toast.style = Toast.Style.Failure;
        toast.title = "Failed to create deadline";
        toast.message = message;
      }
    },
    validation: {
      title: FormValidation.Required,
      due_date: (value) => {
        if (!value || value.trim().length === 0) return "Due date is required";
      },
    },
  });

  function displayName(member: GuildMember): string {
    return member.nick ?? member.global_name ?? member.username;
  }

  return (
    <Form
      actions={
        <ActionPanel>
          <Action.SubmitForm title="Create Deadline" onSubmit={handleSubmit} />
        </ActionPanel>
      }
    >
      <Form.TextField
        {...itemProps.title}
        title="Title"
        placeholder="e.g. Submit quarterly report"
      />
      <Form.TextField
        {...itemProps.due_date}
        title="Due Date"
        placeholder='e.g. 2026-06-15 or "15 Jun 2026 17:00" or "2026-06-15 AoE"'
        info="Accepts the same flexible formats as the Discord /deadline add command."
      />
      <Form.TextArea
        {...itemProps.description}
        title="Description"
        placeholder="Optional description or notes"
      />
      <Form.Separator />
      <Form.TagPicker
        {...itemProps.member_ids}
        title="Members"
        placeholder="Type to filter members..."
        isLoading={isSearching}
      >
        {(memberResults ?? []).map((m) => (
          <Form.TagPicker.Item key={m.id} value={m.id} title={displayName(m)} />
        ))}
      </Form.TagPicker>
    </Form>
  );
}

export default withAccessToken({ authorize })(CreateDeadline);
