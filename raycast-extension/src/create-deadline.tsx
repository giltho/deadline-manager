import { Action, ActionPanel, Form, showToast, Toast, useNavigation } from "@raycast/api";
import { useForm, FormValidation, withAccessToken, usePromise } from "@raycast/utils";
import { createDeadline, searchMembers, type GuildMember } from "./api";
import { authorize } from "./oauth";

interface FormValues {
  title: string;
  due_date: string;
  description: string;
  member_search: string;
}

interface Props {
  onCreated?: () => void;
}

function CreateDeadline({ onCreated }: Props) {
  const { pop } = useNavigation();

  const { isLoading: isSearching, data: memberResults, revalidate: revalidateSearch } = usePromise(
    async (query: string) => {
      if (!query || query.trim().length < 1) return [];
      return searchMembers(query.trim(), 10);
    },
    [""],
  );

  const { handleSubmit, itemProps, values, setValue } = useForm<FormValues>({
    async onSubmit(vals) {
      const toast = await showToast({ style: Toast.Style.Animated, title: "Creating deadline..." });
      try {
        await createDeadline({
          title: vals.title.trim(),
          due_date: vals.due_date.trim(),
          description: vals.description.trim() || undefined,
          member_ids: [], // members are not yet wired up via the search field
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
      <Form.TextField
        id="member_search"
        title="Search Members"
        placeholder="Type a username to search..."
        value={values.member_search}
        onChange={(q) => {
          setValue("member_search", q);
          revalidateSearch(q);
        }}
        info="Search guild members to view results below. Member assignment is shown here as a read-only preview."
      />
      {!isSearching && memberResults && memberResults.length > 0 && (
        <Form.Description
          title="Results"
          text={memberResults.map((m) => `• ${displayName(m)} (${m.id})`).join("\n")}
        />
      )}
      {isSearching && <Form.Description title="" text="Searching..." />}
    </Form>
  );
}

export default withAccessToken({ authorize })(CreateDeadline);
