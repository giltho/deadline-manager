import { Action, ActionPanel, Form, showToast, Toast, useNavigation } from "@raycast/api";
import { useForm, FormValidation, withAccessToken, usePromise } from "@raycast/utils";
import { editDeadline, getAllMembers, type DeadlineResponse, type GuildMember } from "./api";
import { authorize } from "./oauth";

interface FormValues {
  new_title: string;
  due_date: string;
  description: string;
  member_ids: string[];
}

interface Props {
  deadline: DeadlineResponse;
  onEdited?: () => void;
}

/** Format a UTC ISO datetime string to a human-readable local string suitable
 *  for pre-filling the due_date field. Uses the same flexible format the backend
 *  accepts: "YYYY-MM-DD HH:MM" in local time. */
function formatForInput(isoUtc: string): string {
  const d = new Date(isoUtc);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

function EditDeadline({ deadline, onEdited }: Props) {
  const { pop } = useNavigation();

  // Load all guild members on mount for TagPicker client-side filtering.
  const { isLoading: isLoadingMembers, data: memberResults } = usePromise(getAllMembers);

  const { handleSubmit, itemProps } = useForm<FormValues>({
    initialValues: {
      new_title: deadline.title,
      due_date: formatForInput(deadline.due_date),
      description: deadline.description ?? "",
      member_ids: deadline.member_ids,
    },
    async onSubmit(vals) {
      const toast = await showToast({ style: Toast.Style.Animated, title: "Saving changes..." });
      try {
        // Only send fields that have actually changed from original values.
        const body: Parameters<typeof editDeadline>[1] = {};

        const trimmedTitle = vals.new_title.trim();
        if (trimmedTitle !== deadline.title) body.new_title = trimmedTitle;

        const trimmedDate = vals.due_date.trim();
        if (trimmedDate !== formatForInput(deadline.due_date)) body.due_date = trimmedDate;

        const trimmedDesc = vals.description.trim();
        const originalDesc = deadline.description ?? "";
        if (trimmedDesc !== originalDesc) body.description = trimmedDesc || null;

        // Always send member_ids so the backend can diff them.
        body.member_ids = vals.member_ids;

        await editDeadline(deadline.id, body);
        toast.style = Toast.Style.Success;
        toast.title = "Deadline updated";
        onEdited?.();
        pop();
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        toast.style = Toast.Style.Failure;
        toast.title = "Failed to update deadline";
        toast.message = message;
      }
    },
    validation: {
      new_title: FormValidation.Required,
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
      navigationTitle={`Edit: ${deadline.title}`}
      actions={
        <ActionPanel>
          <Action.SubmitForm title="Save Changes" onSubmit={handleSubmit} />
        </ActionPanel>
      }
    >
      <Form.TextField
        {...itemProps.new_title}
        title="Title"
        placeholder="e.g. Submit quarterly report"
      />
      <Form.TextField
        {...itemProps.due_date}
        title="Due Date"
        placeholder='e.g. 2026-06-15 or "15 Jun 2026 17:00" or "2026-06-15 AoE"'
        info="Accepts the same flexible formats as the Discord /deadline edit command."
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
        isLoading={isLoadingMembers}
      >
        {(memberResults ?? []).map((m) => (
          <Form.TagPicker.Item key={m.id} value={m.id} title={displayName(m)} />
        ))}
      </Form.TagPicker>
    </Form>
  );
}

export default withAccessToken({ authorize })(EditDeadline);
