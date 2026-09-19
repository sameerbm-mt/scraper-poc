"use client";

import { Building2, ExternalLink, Mail, MapPin, Phone } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { SiteProfile } from "@/lib/api";

interface SiteProfileCardProps {
  profile: SiteProfile;
}

/** How many services/team members to show before collapsing into a count. */
const VISIBLE_SERVICES = 12;

export function SiteProfileCard({ profile }: SiteProfileCardProps) {
  const extraServices = profile.services.length - VISIBLE_SERVICES;

  return (
    <Card className="border-border/70 shadow-sm">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-lg sm:text-xl">
          <Building2 className="text-primary size-5 shrink-0" />
          <span className="break-anywhere">
            {profile.name || profile.domain}
          </span>
          <Badge variant="outline" className="max-w-full truncate">
            {profile.domain}
          </Badge>
        </CardTitle>
        {profile.description ? (
          <CardDescription className="text-pretty">
            {profile.description}
          </CardDescription>
        ) : null}
      </CardHeader>

      <CardContent className="grid gap-6">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Pages" value={profile.page_count.toLocaleString()} />
          <Stat label="Words" value={profile.total_words.toLocaleString()} />
          <Stat
            label="Services"
            value={profile.services_count.toLocaleString()}
          />
          <Stat label="Team" value={profile.team_count.toLocaleString()} />
        </dl>

        {(profile.emails.length > 0 ||
          profile.phones.length > 0 ||
          profile.address) && (
          <Section title="Contact">
            <div className="flex flex-col gap-2 text-sm sm:flex-row sm:flex-wrap sm:gap-x-6">
              {profile.emails.map((email) => (
                <span
                  key={email}
                  className="inline-flex items-start gap-1.5 break-anywhere"
                >
                  <Mail className="text-muted-foreground mt-0.5 size-3.5 shrink-0" />
                  <a
                    href={`mailto:${email}`}
                    className="underline underline-offset-4"
                  >
                    {email}
                  </a>
                </span>
              ))}
              {profile.phones.map((phone) => (
                <span key={phone} className="inline-flex items-start gap-1.5">
                  <Phone className="text-muted-foreground mt-0.5 size-3.5 shrink-0" />
                  <a
                    href={`tel:${phone}`}
                    className="underline underline-offset-4"
                  >
                    {phone}
                  </a>
                </span>
              ))}
              {profile.address ? (
                <span className="inline-flex items-start gap-1.5 break-anywhere">
                  <MapPin className="text-muted-foreground mt-0.5 size-3.5 shrink-0" />
                  {profile.address}
                </span>
              ) : null}
            </div>
          </Section>
        )}

        {profile.socials.length > 0 && (
          <Section title="Social">
            <div className="flex flex-wrap gap-2">
              {profile.socials.map((social) => (
                <a
                  key={social.network}
                  href={social.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="max-w-full"
                >
                  <Badge variant="secondary" className="capitalize">
                    {social.network}
                    <ExternalLink className="size-3" />
                  </Badge>
                </a>
              ))}
            </div>
          </Section>
        )}

        {profile.services.length > 0 && (
          <Section title={`Services (${profile.services_count})`}>
            <div className="flex flex-wrap gap-2">
              {profile.services.slice(0, VISIBLE_SERVICES).map((service) => (
                <a
                  key={service.url}
                  href={service.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  title={service.url}
                  className="max-w-full"
                >
                  <Badge variant="outline" className="max-w-full truncate">
                    {service.name}
                  </Badge>
                </a>
              ))}
              {extraServices > 0 ? (
                <Badge variant="ghost">+{extraServices} more</Badge>
              ) : null}
            </div>
          </Section>
        )}

        {profile.team.length > 0 && (
          <Section title={`Team (${profile.team_count})`}>
            <ul className="grid gap-1.5 text-sm sm:grid-cols-2">
              {profile.team.map((member) => (
                <li
                  key={member.name}
                  className="flex flex-wrap items-baseline gap-x-2"
                >
                  <span className="font-medium">{member.name}</span>
                  {member.role ? (
                    <span className="text-muted-foreground text-xs">
                      {member.role}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {Object.keys(profile.pages_by_type).length > 0 && (
          <Section title="Pages by type">
            <div className="flex flex-wrap gap-2">
              {Object.entries(profile.pages_by_type)
                .sort((a, b) => b[1] - a[1])
                .map(([type, count]) => (
                  <Badge key={type} variant="secondary">
                    {type} · {count}
                  </Badge>
                ))}
            </div>
          </Section>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-muted/50 ring-foreground/5 rounded-lg px-3 py-2.5 ring-1">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-xl font-semibold tabular-nums sm:text-2xl">{value}</dd>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-2">
      <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
        {title}
      </h3>
      {children}
    </div>
  );
}
